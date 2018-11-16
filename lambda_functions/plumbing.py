"""Create SNS topics and cloudwatch events in each region.
Ensure continued publishing to
"""
import boto3
import json
import os

from logging import basicConfig
from logging import getLogger
from logging import INFO
from logging import StreamHandler


logger = getLogger(__name__)
basicConfig(
    level=INFO,
    handlers=[StreamHandler()]
)


EVENT_PATTERN = {
  "source": [
    "aws.guardduty"
  ],
  "detail-type": [
    "GuardDuty Finding"
  ]
}


NORMALIZER_LAMBDA_FUNCTION = os.getenv(
    'NORMALIZER_LAMBDA_FUNCTION',
    'arn:aws:lambda:us-east-1:371522382791:function:gd2md-findingsToMozDef-1SFTWEN8NVU3B'
)


def get_topics(boto_session):
    """Return the list of SNS topics in a given region."""
    client = boto_session.client('sns')
    response = client.list_topics()
    if len(response['Topics']) == 0:
        return []
    else:
        return response['Topics']


def find_or_create_sns_topic(boto_session):
    """Search for the mozilla-gd-plumbing topic and return the arn.  If the topic does not exist create it."""
    client = boto_session.client('sns')
    topics = get_topics(boto_session)
    if len(topics) == 0:
        response = client.create_topic(
            Name='mozilla-gd-plumbing'
        )
    else:
        for topic in get_topics(boto_session):
            if topic['TopicArn'].endswith('mozilla-gd-plumbing') :
                return topic['TopicArn']

            else:
                response = client.create_topic(
                    Name='mozilla-gd-plumbing'
                )

    return response['TopicArn']


def topic_is_subscribed(boto_session):
    """Enumerate the list of subscriptions for a given topic arn and test to see if it contains the normalizer."""
    client = boto_session.client('sns')
    response = client.list_subscriptions_by_topic(
        TopicArn=find_or_create_sns_topic(boto_session)
    )

    if len(response['Subscriptions']) == 0:
        return False
    elif NORMALIZER_LAMBDA_FUNCTION == response['Subscriptions'][0]['Endpoint']:
        return True
    else:
        return False


def subscribe_to_normalization_function(boto_session):
    """Add a subscription to the current topic for the lambda function that does data transformation."""
    client = boto_session.client('sns')
    response = client.subscribe(
        TopicArn=find_or_create_sns_topic(boto_session),
        Protocol='lambda',
        Endpoint=NORMALIZER_LAMBDA_FUNCTION,
    )
    return response


def ensure_topic_subscriptions(boto_session):
    """Ensure the sns topic is subscribed to the normalization lambda."""
    if topic_is_subscribed(boto_session):
        pass
    else:
        print(subscribe_to_normalization_function(boto_session))


def get_all_rules(boto_session):
    """Search for the mozilla-gd-plumbing rule only.  Returns a list of one."""
    client = boto_session.client('events')
    response = client.list_rules(NamePrefix='mozilla-gd-plumbing')
    return response['Rules']


def setup_guardduty_plumbing(boto_session):
    """Create the cloudwatch event rule."""
    client = boto_session.client('events')
    response = client.put_rule(
        Name='mozilla-gd-plumbing',
        EventPattern=json.dumps(EVENT_PATTERN),
        State='ENABLED',
        Description='Send all guardDuty findings to SNS for SIEM normalization.',
    )
    return response


def setup_sns_publishing(boto_session):
    """Add teh sns topic in a given region to the cloudwatch event rule."""
    client = boto_session.client('events')
    response = client.put_targets(
        Rule='mozilla-gd-plumbing',
        Targets=[
            {
                'Arn': find_or_create_sns_topic(boto_session),
                'Id': 'gd2MdSNS',
            }
        ]
    )
    return response


def get_all_aws_regions(boto_session):
    ec2 = boto_session.client('ec2')
    return ec2.describe_regions()


def handle(event=None, context=None):
    logger.info('Activating guardDuty plumbing.')
    boto_session = boto3.session.Session()
    for region in get_all_aws_regions(boto_session)['Regions']:
        logger.info('Attempting cross region setup for {}.'.format(region['RegionName']))
        region_session = boto3.session.Session(region_name=region['RegionName'])
        logger.info('Ensuring guardduty cloudwatch event exists for {}.'.format(region['RegionName']))
        setup_guardduty_plumbing(boto_session)
        logger.info('Ensuring guardduty sns topic exists for {}.'.format(region['RegionName']))
        setup_sns_publishing(boto_session)
        logger.info(
            'Ensuring guardduty sns topic is subscribed to the normalization function for {}.'.format(
                region['RegionName']
            )
        )
        ensure_topic_subscriptions(region_session)
        logger.info('Run complete for region: {}'.format(region['RegionName']))


if __name__ == "__main__":
    handle()
