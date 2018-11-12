# Deployment Plan

## Setup new member IAM role

* Update the security audit/incident response CloudFormation template to add
  another role
  * GuardDutyInvitationAcceptor
    * guardduty:ListDetectors
    * guardduty:CreateDetector
    * guardduty:AcceptInvitation
    * guardduty:GetDetector
    * guardduty:GetInvitationsCount
    * guardduty:GetMasterAccount
    * guardduty:UpdateDetector

## Setup GuardDuty master in all regions
    
* Deploy GuardDuty master accounts in infosec-prod all regions
* guardduty:CreateDetector in each region to create a local infosec-prod detector

## Create lambda GuardDuty account linker

* Create Lambda function in infosec-prod which wakes up each night, 3 times in a
 row with 5 minutes between each run via CloudWatch and
    * Assume role 329567179436:Infosec-Organization-Reader
        * Fetch list of accounts and email addresses : organizations:ListAccounts
    * Iterate over each GuardDuty region
        * Get list of existing GuardDuty member accounts guardduty:ListMembers
        for this region
        * Iterate over list from organizations:ListAccounts, excluding any accounts
        that were returned from guardduty:ListMembers with RelationshipStatus of
        'ENABLED'
          * Assume GuardDutyInvitationAcceptor IAM role (or reuse a previously
          assumed role during a different region iteration) in each target account
            * guardduty:ListDetectors to see if there's an existing detector
            * guardduty:CreateDetector to create a new one
            * record the detector_id from the listing or the creation
        * guardduty:CreateMembers passing it a list of every GuardDuty
        account which did not show up in the results of guardduty:ListMembers but
        which is in the Organization
        * Note : At this point any newly created members will be processing and
        we'll skip over them this run
        * Note : Here we'll deal with newly created members from the last run
        * For each member account that has a RelationshipStatus of 'CREATED'
            * guardduty:InviteMembers passing the list of all CREATED members
        * Note : At this point the invitations will take time to propagate and those
        accounts will be picked up in the next run
        * Note : Here we'll deal with newly invited members from the last run
        * For each member account that has a RelationshipStatus of 'INVITED'
            * Reuse previously assumed GuardDutyInvitationAcceptor IAM role for the
            account
                * For each invite in guardduty:ListInvitations with an accountId of
                infosec-prod
                    * guardduty:AcceptInvitation
                    * (not using the assumed role) emit an SNS event reporting that
                    the invite was accepted

# Outcome

* Any new accounts created in the Organization will
  * have detectors created in every region
  * be created as a member in the infosec-prod GuardDuty master in every region
  * be invited to be a member of the infosec-prod GuardDuty master in every region
  * accept the invitation to be a member in every region
  * emit SNS notifications for each accepted invite

# The multiple executions of the Lambda function

* Execution 1 will
  * create detectors in every region for every new account
  * create the new account as a member in the infosec-prod GuardDuty master in every region
* Execution 2 will
  * invite the newly created member to connect to the master
* Execution 3 will
  * accept the invitation to connect to the master

