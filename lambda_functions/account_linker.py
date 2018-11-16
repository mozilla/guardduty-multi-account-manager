import boto3
import logging
import os
from boto3.dynamodb.types import TypeDeserializer
from boto3.dynamodb.transform import TransformationInjector

logger = logging.getLogger(__name__)
DYNAMODB_TABLE_NAME = os.environ.get(
    'DYNAMODB_TABLE_NAME', 'cloudformation-stack-emissions')
DB_CATEGORY = os.environ.get(
    'DB_CATEGORY', 'GuardDuty Multi Account Member Role')


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
                   DisassociateFromMasterAccount
        EMAILVERIFICATIONINPROGRESS : Member invited by master with
                                      DisableEmailNotification=False
        EMAILVERIFICATIONFAILED :

        :param args: Relationship status
        :return: List of account IDs
        """
        return [k for k, v in self.all_members.items() if v in args]


def get_session(role_arn=None):
    """Return a boto session either for the current IAM Role or for an assumed
    role if role_arn is passed

    :param role_arn: An ARN of an AWS IAM role to assume
    :return: Boto session
    """
    if role_arn is not None:
        client = boto3.client('sts')
        credentials = client.assume_role(
            RoleArn=role_arn,
            RoleSessionName='GuardDutyMultiAccountManager',
            DurationSeconds=90
        )['Credentials']
        boto_session = boto3.session.Session(
            aws_access_key_id=credentials['AccessKeyId'],
            aws_secret_access_key=credentials['SecretAccessKey'],
            aws_session_token=credentials['SessionToken']
        )
    else:
        boto_session = boto3.session.Session()
    return boto_session


def create_detector(boto_session, region_name):
    gd = boto_session.client('guardduty', region_name=region_name)
    response = gd.create_detector(
        Enable=True,
        FindingPublishingFrequency='FIFTEEN_MINUTES'
    )
    return response


def get_all_detectors(boto_session, region_name):
    gd = boto_session.client('guardduty', region_name=region_name)
    response = gd.list_detectors()
    return response


def find_or_create_detector(boto_session, region_name):
    resp = get_all_detectors(boto_session, region_name)
    if len(resp['DetectorIds']) > 0:
        return resp['DetectorIds'][0]
    else:
        logger.info(
            '{} : Creating detector'.format(
                region_name))
        resp = create_detector(boto_session, region_name)
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
    accounts = {}
    map(accounts.update, {x['Accounts']['Id']: x['Accounts']['Email']
                          for x in paginator.paginate()})
    return accounts


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
        items.extend([x['Items'] for x in page])

    return {x['aws-account-id']: x['GuardDutyMemberAccountIAMRoleArn']
            for x in items
            if x.get('category') == DB_CATEGORY
            and {('aws-account-id',
                  'GuardDutyMemberAccountIAMRoleArn')} <= set(x)}


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
        * For members with a pending invitationaAccept the invitation in the
          member account

    Set environment variables
      * ORGANIZATION_IAM_ROLE_ARN : IAM Role ARN to assume to reach AWS
        Organization parent account

    :param event: Lambda event object
    :param context: Lambda context object
    """
    local_boto_session = get_session()
    local_account_id = boto3.client('sts').get_caller_identity()["Account"]
    guardduty_regions = local_boto_session.get_available_regions('guardduty')
    default_region = 'us-west-2'
    org_boto_session = get_session(os.environ.get('ORGANIZATION_IAM_ROLE_ARN'))

    # Fetch the accounts list from AWS Organizations
    organizations_account_id_map = get_account_id_email_map_from_organizations(
        org_boto_session, region_name=default_region)
    logger.debug(
        'Organization account ID map: {}'.format(organizations_account_id_map))

    # Filter out accounts if ACCOUNT_FILTER_LIST is set
    for account_id in os.environ.get('ACCOUNT_FILTER_LIST', []):
        del organizations_account_id_map[account_id]
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
            local_boto_session, region_name)
        logger.info(
            '{} : GuardDuty detector exists with Id: {}'.format(
                region_name, local_detector_id))

        # Fetch the GuardDuty members list
        client = local_boto_session.client(
            'guardduty', region_name=region_name)
        response = client.get_members(
            AccountIds=account_id_role_arn_map.keys(),
            DetectorId=local_detector_id)
        members = {x['AccountId']: x['RelationshipStatus']
                   for x in response['Members']}
        logger.debug('{} : Member dict : {}'.format(region_name, members))

        # Create a get_members function to work with the members list
        get_members = GetMembers(members)

        # Create members for accounts that haven't been created yet
        account_details = [
            {'AccountId': account_id, 'Email': email}
            for account_id, email in organizations_account_id_map.items()
            if account_id not in members
            or account_id in get_members('REMOVED')]
        if account_details:
            logger.info(
                '{} : Creating members : {}'.format(
                    region_name, account_details))
            client.create_members(
                AccountDetails=account_details,
                DetectorId=local_detector_id)

        # Invite members that have been created
        account_ids_to_invite = get_members('CREATED', 'RESIGNED')
        if account_ids_to_invite:
            logger.info(
                '{} : Inviting members : {}'.format(
                    region_name, account_ids_to_invite))
            client.invite_members(
                AccountIds=account_ids_to_invite,
                DetectorId=local_detector_id,
                DisableEmailNotification=True)

        for account_id, email in organizations_account_id_map.items():
            boto_session = get_session(account_id_role_arn_map[account_id])
            if account_id in get_members('DISABLED'):
                # For DISABLED members
                # Update member account detector to enabled
                detector_id = find_or_create_detector(
                    boto_session, region_name)
                logger.info(
                    '{} : {} : Updating member to re-enable detector'.format(
                        region_name, account_id))
                client.update_detector(
                    DetectorId=detector_id,
                    Enable=True)
            if account_id in get_members(
                    'RESIGNED', 'REMOVED', 'INVITED',
                    'EMAILVERIFICATIONINPROGRESS', 'EMAILVERIFICATIONFAILED'):
                # Get or create a detector in the member account
                detector_id = find_or_create_detector(
                    boto_session, region_name)
                if account_id in get_members(
                        'RESIGNED', 'INVITED', 'EMAILVERIFICATIONINPROGRESS',
                        'EMAILVERIFICATIONFAILED'):
                    # For members with a pending invitation
                    # Accept the invitation in the member account
                    response = client.list_invitations()
                    # This assumes that if the master things the member is
                    # INVITED then the member will have a listed pending
                    # invitation
                    invitation_id = next(
                        x['InvitationId'] for x in response['Invitations']
                        if x['AccountId'] == local_account_id)
                    logger.info(
                        '{} : {} : Member accepting invite'.format(
                            region_name, account_id))
                    client.accept_invitation(
                        DetectorId=detector_id,
                        InvitationId=invitation_id,
                        MasterId=local_account_id)
