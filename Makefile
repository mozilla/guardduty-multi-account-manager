ROOT_DIR	:= $(shell dirname $(realpath $(lastword $(MAKEFILE_LIST))))
PARENTDIR       := $(realpath ../)
S3_BUCKET_NAME  := infosec-public-data
S3_BUCKET_PATH	:= cf/guardduty-multi-account-manager
S3_BUCKET_URI	:= s3://$(S3_BUCKET_NAME)/$(S3_BUCKET_PATH)

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
