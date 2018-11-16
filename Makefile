ROOT_DIR	:= $(shell dirname $(realpath $(lastword $(MAKEFILE_LIST))))
PARENTDIR       := $(realpath ../)
AWS_REGION = us-west-2
S3_BUCKET_NAME  := infosec-public-data
S3_BUCKET_PATH	:= cf/guardduty-multi-account-manager
S3_BUCKET_URI	:= s3://$(S3_BUCKET_NAME)/$(S3_BUCKET_PATH)

all:
	@echo 'Available make targets:'
	@grep '^[^#[:space:]].*:' Makefile

.PHONY: test
test:
	py.test tests/ --capture=no

# --ignore-checks=E2502 : https://github.com/awslabs/cfn-python-lint/issues/408
.PHONY: cflint test
test: cflint
cflint: ## Verify the CloudFormation template pass linting tests
	-cfn-lint --ignore-checks=E2502 cloudformation/*.yml

.PHONY: upload-templates
upload-templates:
	@export AWS_REGION=$(AWS_REGION)
	aws s3 sync cloudformation/ $(S3_BUCKET_URI) --acl public-read

.PHONY: upload-gd2md-lambda
upload-gd2md-lambda:
	@export AWS_REGION=$(AWS_REGION)
	zip lambda_functions/gd2md.zip lambda_functions/normalization.py
	aws s3 cp lambda_functions/gd2md.zip s3://infosec-public-data/lambda/gd2md.zip --acl public-read
	rm lambda_functions/gd2md.zip

.PHONY: upload-plumbing-lambda
upload-plumbing-lambda:
	@export AWS_REGION=$(AWS_REGION)
	zip lambda_functions/plumbing.zip lambda_functions/plumbing.py
	aws s3 cp lambda_functions/plumbing.zip s3://infosec-public-data/lambda/plumbing.zip --acl public-read
	rm lambda_functions/plumbing.zip

.PHONY: upload-templates create-stack
create-stack:
	@export AWS_REGION=$(AWS_REGION)
	aws cloudformation create-stack --stack-name guardduty-multi-account-manager --template-url https://s3.amazonaws.com/infosec-public-data/cf/guardduty-multi-account-manager/guardduty-multi-account-manager-parent.yml

.PHONY: upload-templates create-stack
create-stackset-roles:
	@export AWS_REGION=$(AWS_REGION)
	aws cloudformation create-stack --stack-name stackset-administrative-roles --template-url https://s3.amazonaws.com/cloudformation-stackset-sample-templates-us-east-1/AWSCloudFormationStackSetAdministrationRole.yml
