# GuardDuty Multi-Account Manager
A reusable implementation Mozilla's use of GuardDuty multi account
setup with event normalization.

## Architecture

!['docs/dgram.png'](docs/dgram.png)

> Above is an example architecture for a master account with a member account. 
> Note: The member account has GuardDuty detectors in every region as does the 
> master account.

## Why This?

As a multi-account user of Amazon Web Services you have a few choices when
deciding to turn on GuardDuty across your accounts.

Your options are:

1. Stack Sets
2. Human invitations
3. Something else.

Due to the nature of stack sets and the distributed governance of Mozilla it
breaks our trust model to grant the needed permissions to run stack sets.
Human behavior consistently generates inconsistent results.

This is why we elected to create GuardDuty Multi-Account Manager

## What is it?

GuardDuty Multi-Account Manager is a series of lambda functions designed to do
the following:

* Enable GuardDuty Masters in all AWS Regions present and future.
* Empower account owners to decide to enable GuardDuty
* Manage the lifecycle of invitations to the member accounts
* Aggregate all findings from all detectors in all regions, normalize the data,
  and send to a single SQS queue

## How do I deploy it?

__Dependencies__

* AWS Organizations
  * Either run the GuardDuty Multi-Account Manager from within an AWS
    Organizations parent account or
  * Establish an IAM Role in the AWS Organizations parent account that can be
    assumed by the GuardDuty Multi-Account Manager.
    [Example IAM Role](docs/example-organizations-reader-iam-role.yml)
* Deploy the
  [Cloudformation Cross Account Outputs](https://github.com/mozilla/cloudformation-cross-account-outputs/)
  service which allows CloudFormation stacks in other AWS accounts to report
  back output. This is used to convey the
  [GuardDuty Member Account IAM Role](cloudformation/guardduty-member-account-role.yml)
  information. Simply deploy the
  [CloudFormation template]((https://github.com/mozilla/cloudformation-cross-account-outputs/cloudformation-sns-emission-consumer.yml))
  to enable it. The stack will output a `SNSTopicARN` which is the SNS Topic
  ARN to configure as the default `SNSArnForPublishingIAMRoleArn` parameter in your
  [`guardduty-member-account-role.yml`](cloudformation/guardduty-member-account-role.yml).
  Before distributing `guardduty-member-account-role.yml` to your intended
  GuardDuty member account owners, set the `SNSArnForPublishingIAMRoleArn` default
  to the value from the deployed `cloudformation-cross-account-outputs` stack's
  `SNSTopicARN` output.

## Getting Started

* Deploy the Cloudformation Stack from
  `cloudformation/guardduty-multi-account-manager-parent.yml` in the master
  account.
* The stack will spin up and create all Master Detectors in all regions, a
  normalization functions, and all SNS Topics with CloudWatch events.

### Onboarding Accounts

1. Ensure that the `SNSTopicARN` default parameter in your
   [`cloudformation/guardduty-member-account-role.yml`](cloudformation/guardduty-member-account-role.yml)
   template is set to the `SNSArnForPublishingIAMRoleArn` value output from the
   earlier deployed
   [Cloudformation Cross Account Outputs CloudFormation template]((https://github.com/mozilla/cloudformation-cross-account-outputs/cloudformation-sns-emission-consumer.yml))
2. Deploy the [`cloudformation/guardduty-member-account-role.yml`](cloudformation/guardduty-member-account-role.yml)
   CloudFormation template in your member AWS account. The account will then
   register with the master account and go through the invitation process 
   automatically for every region.

## License

guardduty-multi-account-manager is Licensed under the
[Mozilla Public License 2.0 ( MPL2.0 )](https://www.mozilla.org/en-US/MPL/2.0/)

## Contributors

* [Gene Wood](https://github.com/gene1wood/)
* [Andrew Krug](https://github.com/andrewkrug/)
