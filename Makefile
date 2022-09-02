ROOT_DIR	:= $(shell dirname $(realpath $(lastword $(MAKEFILE_LIST))))
PARENTDIR       := $(realpath ../)
AWS_REGION = us-west-2
# We only need to publish to the us-west-2 bucket as it uses bucket replication
# to replicate all data to the buckets in other regions
S3_BUCKET_NAME  := public.us-west-2.infosec.mozilla.org
S3_BUCKET_TEMPLATE_PATH	:= guardduty-multi-account-manager/cf
S3_BUCKET_LAMBDA_PATH	:= guardduty-multi-account-manager/lambda
S3_BUCKET_TEMPLATE_URI	:= s3://$(S3_BUCKET_NAME)/$(S3_BUCKET_TEMPLATE_PATH)
S3_BUCKET_LAMBDA_URI	:= s3://$(S3_BUCKET_NAME)/$(S3_BUCKET_LAMBDA_PATH)
PARENT_TEMPLATE_URI	:= https://s3.amazonaws.com/$(S3_BUCKET_NAME)/$(S3_BUCKET_TEMPLATE_PATH)/guardduty-multi-account-manager-parent.yml
LAMBDA_BUCKET_PREFIX	:= $(shell v='$(S3_BUCKET_NAME)'; echo "$${v%%us-west-2*}")
LAMBDA_BUCKET_SUFFIX	:= $(shell v='$(S3_BUCKET_NAME)'; echo "$${v\#\#*us-west-2}")

all:
	@echo 'Available make targets:'
	@grep '^[^#[:space:]].*:' Makefile

.PHONY: test
test:
	py.test tests/ --capture=no

.PHONY: cfn-lint test
test: cfn-lint
cfn-lint: ## Verify the CloudFormation template pass linting tests
	-cfn-lint cloudformation/*.yml

.PHONY: upload-templates
upload-templates:
	@export AWS_REGION=$(AWS_REGION)
	aws s3 sync cloudformation/ $(S3_BUCKET_TEMPLATE_URI) --exclude="*" --include="*.yml"

.PHONY: upload-normalization-lambda
upload-normalization-lambda:
	@export AWS_REGION=$(AWS_REGION)
	zip lambda_functions/normalization.zip lambda_functions/normalization.py
	aws s3 cp lambda_functions/normalization.zip $(S3_BUCKET_LAMBDA_URI)/normalization.zip
	rm lambda_functions/normalization.zip

.PHONY: upload-plumbing-lambda
upload-plumbing-lambda:
	@export AWS_REGION=$(AWS_REGION)
	zip lambda_functions/plumbing.zip lambda_functions/plumbing.py
	aws s3 cp lambda_functions/plumbing.zip $(S3_BUCKET_LAMBDA_URI)/plumbing.zip
	rm lambda_functions/plumbing.zip

.PHONY: upload-invitation_manager-lambda
upload-invitation_manager-lambda:
	zip lambda_functions/invitation_manager.zip lambda_functions/invitation_manager.py
	AWS_REGION=$(AWS_REGION) aws s3 cp lambda_functions/invitation_manager.zip $(S3_BUCKET_LAMBDA_URI)/invitation_manager.zip
	rm lambda_functions/invitation_manager.zip

.PHONY: upload-templates create-stack
create-stack:
	@export AWS_REGION=$(AWS_REGION)

	# $${$(S3_BUCKET_NAME)##us-west-2*}
	# https://github.com/aws/aws-cli/issues/870#issuecomment-51629161
	aws cloudformation create-stack --stack-name guardduty-multi-account-manager \
	  --capabilities CAPABILITY_IAM \
	  --parameters \
	    ParameterKey=CloudFormationTemplatePrefix,ParameterValue=https://s3.amazonaws.com/$(S3_BUCKET_NAME)/$(S3_BUCKET_TEMPLATE_PATH)/ \
	    ParameterKey=LambdaCodeS3BucketNamePrefix,ParameterValue=$(LAMBDA_BUCKET_PREFIX) \
	    ParameterKey=LambdaCodeS3BucketNameSuffix,ParameterValue=$(LAMBDA_BUCKET_SUFFIX) \
	    ParameterKey=LambdaCodeS3Path,ParameterValue=$(S3_BUCKET_LAMBDA_PATH)/ \
	    ParameterKey=OrganizationAccountArns,ParameterValue=\'$(ORGANIZAION_ACCOUNT_ARNS)\' \
	    ParameterKey=AccountFilterList,ParameterValue=$(ACCOUNT_FILTER_LIST) \
	  --template-url $(PARENT_TEMPLATE_URI)

.PHONY: create-invitation-manager-stack
create-invitation-manager-stack:
	AWS_REGION=$(AWS_REGION) aws cloudformation create-stack --stack-name guardduty-invitation-manager \
	  --capabilities CAPABILITY_IAM \
	  --parameters \
	    ParameterKey=LambdaCodeS3BucketNamePrefix,ParameterValue=$(LAMBDA_BUCKET_PREFIX) \
	    ParameterKey=LambdaCodeS3BucketNameSuffix,ParameterValue=$(LAMBDA_BUCKET_SUFFIX) \
	    ParameterKey=LambdaCodeS3Path,ParameterValue=$(S3_BUCKET_LAMBDA_PATH)/ \
	    ParameterKey=OrganizationAccountArns,ParameterValue=\'$(ORGANIZAION_ACCOUNT_ARNS)\' \
	    ParameterKey=AccountFilterList,ParameterValue=$(ACCOUNT_FILTER_LIST) \
	  --template-url https://s3.amazonaws.com/$(S3_BUCKET_NAME)/$(S3_BUCKET_TEMPLATE_PATH)/guardduty-invitation-manager.yml

.PHONY: upload-templates update-stack
update-stack:
	@export AWS_REGION=$(AWS_REGION)
	aws cloudformation update-stack --stack-name guardduty-multi-account-manager \
	  --capabilities CAPABILITY_IAM \
	  --template-url $(PARENT_TEMPLATE_URI)


# To upload to staging and test
# logged into infosec-dev AWS account
#  make upload-templates S3_BUCKET_NAME=public.us-west-2.security.allizom.org
#  make upload-invitation_manager-lambda S3_BUCKET_NAME=public.us-west-2.security.allizom.org
# logged into infosec-prod (because this is the account that's trusted)
#  make create-stack S3_BUCKET_NAME=public.us-west-2.security.allizom.org
# or
#  make create-invitation-manager-stack S3_BUCKET_NAME=public.us-west-2.security.allizom.org ORGANIZAION_ACCOUNT_ARNS=arn:aws:iam::329567179436:role/Infosec-Organization-Reader,arn:aws:iam::943761894018:role/Infosec-Organization-Reader


