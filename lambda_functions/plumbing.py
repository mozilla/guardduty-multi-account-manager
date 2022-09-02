"""Create SNS topics and cloudwatch events in each region.
Ensure continued publishing to
"""
import boto3
import json
import os
import uuid

from botocore.exceptions import ClientError

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
    'arn:aws:lambda:us-east-1:371522382791:function:findingsToMozDef-1O04GFRLK0EJQ'
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


def clean_subscription_list(boto_session):
    """Search for the mozilla-gd-plumbing topic and return the arn.  If the topic does not exist create it."""
    client = boto_session.client('sns')
    response = client.list_subscriptions_by_topic(
        TopicArn=find_or_create_sns_topic(boto_session)
    )
    if len(response['Subscriptions']) == 0:
        pass
    else:
        for i in response['Subscriptions']:
            if NORMALIZER_LAMBDA_FUNCTION != i.get('Endpoint', ''):
                logger.info('Unsubcribing lambda from topic.  Perhaps you re-deployed?')
                response = client.unsubscribe(
                    SubscriptionArn=i['SubscriptionArn']
                )

def topic_is_subscribed(boto_session):
    """Enumerate the list of subscriptions for a given topic arn and test to see if it contains the normalizer."""
    client = boto_session.client('sns')
    response = client.list_subscriptions_by_topic(
        TopicArn=find_or_create_sns_topic(boto_session)
    )

    if len(response['Subscriptions']) == 0:
        return False
    else:
        for i in response['Subscriptions']:
            if NORMALIZER_LAMBDA_FUNCTION == i.get('Endpoint', ''):
                return True
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
        subscribe_to_normalization_function(boto_session)


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
                'Id': 'normalizationSNS',
            }
        ]
    )
    return response


def get_all_aws_regions(boto_session):
    return boto_session.get_available_regions('guardduty')

def add_lambda_permission(region_session, region_name):
    boto_session = boto3.session.Session(region_name='us-east-1')
    client = boto_session.client('lambda')
    try:
        response = client.add_permission(
            Action='lambda:InvokeFunction',
            FunctionName=NORMALIZER_LAMBDA_FUNCTION.split(':')[6],
            Principal='sns.amazonaws.com',
            SourceArn=find_or_create_sns_topic(region_session),
            StatementId='{}-sns-invoke'.format(region_name)
        )
        return response
    except ClientError as e:
        logger.debug(
            'Could not creake invoke permission. Permission already exists in region: {}'.format(e, region_name)
        )



def handle(event=None, context=None):
    logger.info('Activating guardDuty plumbing.')
    boto_session = boto3.session.Session()
    for region in get_all_aws_regions(boto_session):
        logger.info('Attempting cross region setup for {}.'.format(region))
        region_session = boto3.session.Session(region_name=region)
        logger.info('Ensuring guardduty cloudwatch event exists for {}.'.format(region))
        setup_guardduty_plumbing(region_session)
        logger.info('Ensuring guardduty sns topic exists for {}.'.format(region))
        setup_sns_publishing(region_session)
        logger.info(
            'Ensuring guardduty sns topic is subscribed to the normalization function for {}.'.format(
                region
            )
        )
        ensure_topic_subscriptions(region_session)
        clean_subscription_list(region_session)
        add_lambda_permission(region_session, region)
        logger.info('Run complete for region: {}'.format(region))


if __name__ == "__main__":
    handle()
