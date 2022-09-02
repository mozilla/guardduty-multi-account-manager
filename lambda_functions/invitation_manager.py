import boto3
import logging
import os
from boto3.dynamodb.types import TypeDeserializer
from boto3.dynamodb.transform import TransformationInjector

root = logging.getLogger()
if root.handlers:
    for handler in root.handlers:
        root.removeHandler(handler)

logging.basicConfig(
    level=logging.INFO,
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)
logging.getLogger('botocore').setLevel(logging.CRITICAL)
logging.getLogger('urllib3').setLevel(logging.CRITICAL)

DYNAMODB_TABLE_NAME = os.environ.get(
    'DYNAMODB_TABLE_NAME', 'cloudformation-stack-emissions')
DB_CATEGORY = os.environ.get(
    'DB_CATEGORY', 'GuardDuty Multi Account Member Role')
ORGANIZATION_IAM_ROLE_ARNS = os.environ.get(
    'ORGANIZATION_IAM_ROLE_ARNS')
ACCOUNT_FILTER_LIST = os.environ.get('ACCOUNT_FILTER_LIST', '')


class GetMembers:
    """Return a function which allows for filtering the member dict"""

    def __init__(self, all_members):
        self.all_members = all_members

    def __call__(self, *args):
        """Return the account IDs of accounts with one of the passed
        relationship statuses

        CREATED  : Member created by master but master hasn't invited member
        INVITED  : Member invited by master with DisableEmailNotification=True
        DISABLED : Member has accepted invitation but detector has been updated
                   to Enable=False
        ENABLED  : Member has accepted invitation
        REMOVED  : Member has accepted invitation but detector has been deleted
        RESIGNED : Member that had accepted the invitation, then later called
                   DisassociateFromMasterAccount or deselected the "Accept"
                   button in the web console
        EMAILVERIFICATIONINPROGRESS : Member invited by master with
                                      DisableEmailNotification=False
        EMAILVERIFICATIONFAILED :
        Not present : Member's never been created or member has resigned, and
                      then clicked the `x` in the web console to delete
                      themselves

        :param args: Relationship status
        :return: List of account IDs
        """
        return [k for k, v in self.all_members.items()
                if v.lower() in [x.lower() for x in args]]


def get_session(role_arn=None):
    """Return a boto session either for the current IAM Role or for an assumed
    role if role_arn is passed

    :param role_arn: An ARN of an AWS IAM role to assume
    :return: Boto session
    """
    if role_arn is not None:
        client = boto3.client('sts')
        try:
            credentials = client.assume_role(
                RoleArn=role_arn,
                RoleSessionName='GuardDutyMultiAccountManager',
                DurationSeconds=900
            )['Credentials']
            boto_session = boto3.session.Session(
                aws_access_key_id=credentials['AccessKeyId'],
                aws_secret_access_key=credentials['SecretAccessKey'],
                aws_session_token=credentials['SessionToken']
            )
        except:
            logging.error('Failed to assume role %s' % role_arn)
            raise
    else:
        boto_session = boto3.session.Session()
    return boto_session


def create_detector(boto_session, region_name, account_id=''):
    gd = boto_session.client('guardduty', region_name=region_name)
    response = gd.create_detector(
        Enable=True,
        # FindingPublishingFrequency='FIFTEEN_MINUTES'
        # We need a newer version of boto3 to support this argument
        # https://github.com/boto/botocore/commit/31f3dfd37a89b018f818807d9977d6d4e5090467
    )
    logger.info(
        '{} : {} : Created detector {}'.format(
            region_name, account_id, response['DetectorId']))
    return response


def get_all_detectors(boto_session, region_name):
    gd = boto_session.client('guardduty', region_name=region_name)
    response = gd.list_detectors()
    return response


def find_or_create_detector(boto_session, region_name, account_id):
    resp = get_all_detectors(boto_session, region_name)
    if len(resp['DetectorIds']) > 0:
        return resp['DetectorIds'][0]
    else:
        resp = create_detector(boto_session, region_name, account_id)
        return resp['DetectorId']


def get_account_id_email_map_from_organizations(boto_session, region_name):
    """List AWS Organization child accounts and return a map of account IDs to
    account email addresses.

    :param boto_session: Boto session
    :param region_name: AWS region name
    :return: dict with account ID keys and email address values
    """
    client = boto_session.client('organizations', region_name=region_name)
    paginator = client.get_paginator('list_accounts')
    accounts = []
    list(map(accounts.extend, [x['Accounts'] for x in paginator.paginate()]))
    account_map = {x['Id']: x['Email'] for x in accounts}
    return account_map


def get_account_role_map(boto_session, region_name):
    """Fetch the ARNs of all the IAM Roles which people have created in other
    AWS accounts which are inserted into DynamoDB with
    http://github.com/gene1wood/cloudformation-cross-account-outputs

    :return: dict with account ID keys and IAM Role ARN values
    """

    client = boto_session.client('dynamodb', region_name=region_name)

    paginator = client.get_paginator('scan')
    service_model = client._service_model.operation_model('Scan')
    trans = TransformationInjector(deserializer=TypeDeserializer())
    items = []
    for page in paginator.paginate(TableName=DYNAMODB_TABLE_NAME):
        trans.inject_attribute_value_output(page, service_model)
        items.extend([x for x in page['Items']])

    return {x['aws-account-id']: x['GuardDutyMemberAccountIAMRoleArn']
            for x in items
            if x.get('category') == DB_CATEGORY
            and {'aws-account-id',
                 'GuardDutyMemberAccountIAMRoleArn'} <= set(x)}


def tear_down_members(account_ids):
    local_boto_session = get_session(os.environ.get('MANAGER_IAM_ROLE_ARN'))
    local_account_id = boto3.client('sts').get_caller_identity()["Account"]
    guardduty_regions = local_boto_session.get_available_regions('guardduty')
    account_id_role_arn_map = get_account_role_map(
        local_boto_session, 'us-west-2')
    for region_name in guardduty_regions:
        detector_id = get_all_detectors(
            local_boto_session, region_name)['DetectorIds'][0]
        client = local_boto_session.client(
            'guardduty', region_name=region_name)
        client.delete_members(
            AccountIds=account_ids,
            DetectorId=detector_id
        )
        logger.info('{}: Deleted member {} from master detector {}'.format(
            region_name, account_ids, detector_id))

        for account_id in account_ids:
            member_boto_session = get_session(
                account_id_role_arn_map[account_id])
            member_client = member_boto_session.client(
                'guardduty', region_name=region_name)
            for member_detector_id in get_all_detectors(
                    member_boto_session, region_name)['DetectorIds']:
                try:
                    member_client.disassociate_from_master_account(
                        DetectorId=member_detector_id)
                    logger.info(
                        '{}: {} : Dissasociated member dector id {} from '
                        'master'.format(
                            region_name, account_id, member_detector_id))
                except:
                    pass
                try:
                    member_client.delete_detector(
                        DetectorId=member_detector_id)
                    logger.info(
                        '{}: {} : Deleted member detector id {}'.format(
                            region_name, account_id, member_detector_id))
                except:
                    pass
            member_client.delete_invitations(AccountIds=[local_account_id])
            logger.info(
                '{}: {} : Invitation from {} deleted'.format(
                    region_name, account_id, local_account_id))


def handle(event, context):
    """Move all AWS accounts in an AWS Organization which have delegated
    permissions to this account towards a functioning member master
    GuardDuty relationship.

    * Fetch the accounts list from AWS Organizations
    * Get IAM Role ARNs for each account
    * For each region
      * Ensure that a GuardDuty master detector is created
      * Fetch the GuardDuty members list
      * Create members for accounts that haven't been created yet
      * Invite members that have been created
      * For each account
        * Update member account detector to enabled if DISABLED
        * Get or create a detector in the member account
        * For members with a pending invitation, accept the invitation in the
          member account

    Set environment variables
      * ORGANIZATION_IAM_ROLE_ARN_LIST : Comma delimited list of IAM Role ARNs
        to assume to reach AWS Organization parent accounts
      * ACCOUNT_FILTER_LIST : Space delimited list of account IDs to include.
        If this is provided, only these accounts will be included. If it's not
        provided, all accounts will be included.

    :param event: Lambda event object
    :param context: Lambda context object
    """
    local_boto_session = get_session(os.environ.get('MANAGER_IAM_ROLE_ARN'))
    local_account_id = boto3.client('sts').get_caller_identity()["Account"]
    guardduty_regions = local_boto_session.get_available_regions('guardduty')
    default_region = 'us-west-2'
    organizations_account_id_map = {}
    org_arn_list = (
        [x.strip() for x in ORGANIZATION_IAM_ROLE_ARNS.split(',')]
        if ORGANIZATION_IAM_ROLE_ARNS is not None else [None])
    for org_arn in org_arn_list:
        org_boto_session = get_session(org_arn)

        # Fetch the accounts list from AWS Organizations
        organizations_account_id_map.update(
            get_account_id_email_map_from_organizations(
                org_boto_session, region_name=default_region))

    logger.debug(
        'Organization account ID map: {}'.format(organizations_account_id_map))

    # Filter accounts to only those in ACCOUNT_FILTER_LIST
    if ACCOUNT_FILTER_LIST:
        organizations_account_id_map = {
            k: v for k, v in organizations_account_id_map.items()
            if k in ACCOUNT_FILTER_LIST.split()}
        logger.debug(
            'Filtered organization account ID map: {}'.format(
                organizations_account_id_map))

    # Get IAM Role ARNs for each account
    account_id_role_arn_map = get_account_role_map(
        local_boto_session, default_region)
    logger.debug(
        'Account ID IAM Role map: {}'.format(account_id_role_arn_map))

    for region_name in guardduty_regions:
        # Ensure that a GuardDuty master detector is created
        local_detector_id = find_or_create_detector(
            local_boto_session, region_name, local_account_id)

        # Fetch the GuardDuty members list
        client = local_boto_session.client(
            'guardduty', region_name=region_name)
        list_of_members = [
            y for sublist in [
                x['Members'] for x in client.get_paginator(
                    'list_members').paginate(
                    DetectorId=local_detector_id, OnlyAssociated="FALSE")]
            for y in sublist]
        members = {x['AccountId']: x['RelationshipStatus']
                   for x in list_of_members}
        logger.debug('{} : Member dict : {}'.format(region_name, members))

        # Create a get_members function to work with the members list
        get_members = GetMembers(members)

        # Create members for accounts that haven't been created yet
        account_details = [
            {'AccountId': account_id, 'Email': email}
            for account_id, email in organizations_account_id_map.items()
            if account_id in account_id_role_arn_map.keys() and
            (account_id not in members
             or account_id in get_members('REMOVED'))]
        if account_details:
            client.create_members(
                AccountDetails=account_details,
                DetectorId=local_detector_id)
            logger.info(
                '{} : Members created : {}'.format(
                    region_name, account_details))

        # Delete members that got stuck at email verification
        account_ids_to_delete = get_members('EMAILVERIFICATIONFAILED')
        if account_ids_to_delete:
            client.delete_members(
                AccountIds=account_ids_to_delete,
                DetectorId=local_detector_id)
            logger.info(
                '{} : Member deleted due to email verification failure : {}'.format(
                    region_name, account_ids_to_delete))

        # Invite members that have been created
        account_ids_to_invite = get_members('CREATED', 'RESIGNED')
        if account_ids_to_invite:
            client.invite_members(
                AccountIds=account_ids_to_invite,
                DetectorId=local_detector_id,
                DisableEmailNotification=True)
            logger.info(
                '{} : Member invited : {}'.format(
                    region_name, account_ids_to_invite))

        for account_id in (set(organizations_account_id_map.keys())
                           & set(account_id_role_arn_map.keys())):
            boto_session = get_session(account_id_role_arn_map[account_id])
            member_client = boto_session.client(
                'guardduty', region_name=region_name)
            if account_id in get_members('DISABLED'):
                # For DISABLED members
                # Update member account detector to enabled

                detector_id = find_or_create_detector(
                    boto_session, region_name, account_id)
                member_client.update_detector(
                    DetectorId=detector_id,
                    Enable=True)
                logger.info(
                    '{} : {} : Member updated to re-enable detector'.format(
                        region_name, account_id))
            if account_id in get_members(
                    'RESIGNED', 'REMOVED', 'INVITED',
                    'EMAILVERIFICATIONINPROGRESS'):
                # Get or create a detector in the member account
                detector_id = find_or_create_detector(
                    boto_session, region_name, account_id)
                if account_id in get_members(
                        'RESIGNED', 'INVITED', 'EMAILVERIFICATIONINPROGRESS'):
                    # For members with a pending invitation
                    # Accept the invitation in the member account
                    response = member_client.list_invitations()
                    invitation_id = next((
                        x['InvitationId'] for x in response['Invitations']
                        if x['AccountId'] == local_account_id), None)
                    if invitation_id is not None:
                        member_client.accept_invitation(
                            DetectorId=detector_id,
                            InvitationId=invitation_id,
                            MasterId=local_account_id)
                        logger.info('{} : {} : Accepted member invite on their'
                                    ' behalf'.format(region_name, account_id))
                    else:
                        logger.error(
                            '{} : {} : GuardDuty parent reports member '
                            'RelationshipStatus of {} however member reports '
                            'pending invitations of {}'.format(
                                region_name, account_id, members[account_id],
                                response['Invitations']))
