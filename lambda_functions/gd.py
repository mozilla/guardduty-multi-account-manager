import boto3
import logging


logger = logging.getLogger(__name__)
dynamodb_table_name = cloudformation-stack-emissions


def get_session():
    return boto3.session.Session()


def get_all_aws_regions(boto_session):
    ec2 = boto_session.client('ec2')
    return ec2.describe_regions()


def create_detector(boto_session, region_name):
    gd = boto_session.client('guardduty', region_name=region_name)
    response = gd.create_detector(
        Enable=True,
        FindingPublishingFrequency='FIFTEEN_MINUTES'
    )
    return response


def delete_detector(boto_session, region_name, detector_id):
    gd = boto_session.client('guardduty', region_name=region_name)
    response = gd.delete_detector(
        DetectorId=detector_id
    )
    return response


def get_all_detectors(boto_session, region_name, max_results):
    gd = boto_session.client('guardduty', region_name=region_name)
    response = gd.list_detectors(
        MaxResults=max_results
    )
    return response


def find_or_create_detector(boto_session, region_name, max_results):
    resp = get_all_detectors(boto_session, region_name, max_results)
    if len(resp['DetectorIds']) > 0:
        return resp['DetectorIds'][0]
    else:
        resp = create_detector(boto_session, region_name)
        return resp['DetectorId']


def get_accounts_from_organizations(boto_session, region_name):
    all_accounts = {'Accounts': []}
    client = boto_session.client('organizations')

    response = client.list_accounts(
        MaxResults=10
    )

    for account in response.get('Accounts'):
        all_accounts['Accounts'].append(account)

    while response.get('NextToken', None):
        response = client.list_accounts(
            NextToken='string',
            MaxResults=10
        )

        for account in respone.get('Accounts'):
            all_accounts['Accounts'].append(account)

    return all_accounts


def invite_member_account(boto_session, region_name, account_data_structure, detector_id):
    gd = boto_session.client('guardduty', region_name=region_name)
    account_id = account_data_structure.get('Id')

    response = gd.invite_members(
        AccountIds=[
            account_id
        ],
        DetectorId=detector_id,
        DisableEmailNotification=True
    )

    return response


def account_is_member_of_detector(boto_session, region_name, detector_id, account_id):
    gd = boto_session.client('guardduty', region_name=region_name)
    response = gd.get_members(
        AccountIds=[
            account_id
        ],
        DetectorId=detector_id
    )

    if len(response['Members']) > 0:
        return True
    else:
        return False


def get_list_of_roles():
    dynamodb = boto3.resource('dynamodb', region_name='us-west-2')



def handle(event, context):
    boto_session = get_session()
    response = get_all_aws_regions(boto_session)
    default_region = 'us-west-2'
    # XXX TBD assume the organizations role here

    # Pull back the accounts list from AWSOrganizations
    organizations_accounts = get_accounts_from_organizations(boto_session, region_name=default_region)

    # Ensure that a guardDuty master is created in every region.
    for region in response['Regions']:
        region_name = region['RegionName']
        result = find_or_create_detector(boto_session, region_name, max_results=len(response['Regions']))
        logger.info('GuardDuty detector exists in region: {}, with Id: {}'.format(region, result))

        for account in organizations_accounts['Accounts']:
            # check if the account is already a member of the detector
            is_member = account_is_member_of_detector(boto_session, region_name, detector_id=result, account_id=account['Id'])

            if is_member:
                logger.info('Account: {} is already member of the guardDuty setup.'.format(account['Id']))
                continue
            else:
                # assume guardduty management role in this member_account_session for example
                logger.info('Assuming the guardDuty role for the account: {}'.format(account['Id']))


                # running find or create for the detector in region
                logger.info(
                    'Ensuring detector is present in the region: {} for account: {}'.format(region_name, account['Id'])
                )

                # create a membership using the current boto session


                # send an invite using the boto_session from the running role


                # Get the role arn for the account id from the dynamodb table
