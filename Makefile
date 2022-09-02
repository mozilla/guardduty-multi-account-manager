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
	@export AWS_REGION=$(AWS_REGION)
	zip lambda_functions/invitation_manager.zip lambda_functions/invitation_manager.py
	aws s3 cp lambda_functions/invitation_manager.zip $(S3_BUCKET_LAMBDA_URI)/invitation_manager.zip
	rm lambda_functions/invitation_manager.zip

.PHONY: upload-templates create-stack
create-stack:
	@export AWS_REGION=$(AWS_REGION)
	aws cloudformation create-stack --stack-name guardduty-multi-account-manager \
	  --capabilities CAPABILITY_IAM \
	  --template-url $(PARENT_TEMPLATE_URI)
