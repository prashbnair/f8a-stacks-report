"""Various utility functions related to S3 storage."""

import json
import os
import logging
import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__file__)


class S3Helper:
    """Helper class for storing reports to S3."""

    def __init__(self):
        """Init method for the helper class."""
        self.region_name = os.environ.get('AWS_S3_REGION') or 'us-east-1'
        self.aws_s3_access_key = os.environ.get('AWS_S3_ACCESS_KEY_ID')
        self.aws_s3_secret_access_key = os.environ.get('AWS_S3_SECRET_ACCESS_KEY')
        self.deployment_prefix = os.environ.get('DEPLOYMENT_PREFIX') or 'dev'
        self.report_bucket_name = os.environ.get('REPORT_BUCKET_NAME')

        if self.aws_s3_secret_access_key is None or self.aws_s3_access_key is None or\
                self.region_name is None or self.deployment_prefix is None:
            raise ValueError("AWS credentials or S3 configuration was "
                             "not provided correctly. Please set the AWS_S3_REGION, "
                             "AWS_S3_ACCESS_KEY_ID, AWS_S3_SECRET_ACCESS_KEY, REPORT_BUCKET_NAME "
                             "and DEPLOYMENT_PREFIX correctly.")
        # S3 endpoint URL is required only for local deployments
        self.s3_endpoint_url = os.environ.get('S3_ENDPOINT_URL') or 'http://localhost'

        self.s3 = boto3.resource('s3', region_name=self.region_name,
                                 aws_access_key_id=self.aws_s3_access_key,
                                 aws_secret_access_key=self.aws_s3_secret_access_key)

    def store_json_content(self, content, bucket_name, obj_key):
        """Store the report content to the S3 storage."""
        try:
            logger.info('Storing the report into the S3 file %s' % obj_key)
            self.s3.Object(bucket_name, obj_key).put(
                Body=json.dumps(content, indent=2).encode('utf-8'))
        except Exception as e:
            logger.exception('%r' % e)

    def read_json_object(self, bucket_name, obj_key):
        """Get the report json object found on the S3 bucket."""
        try:
            obj = self.s3.Object(bucket_name, obj_key)
            result = json.loads(obj.get()['Body'].read().decode('utf-8'))
            return result
        except ClientError as e:
            if e.response['Error']['Code'] == 'NoSuchKey':
                logger.exception('No Such Key %s exists' % obj_key)
            elif e.response['Error']['Code'] == 'NoSuchBucket':
                logger.exception('ERROR - No Such Bucket %s exists' % bucket_name)
            else:
                logger.exception('%r' % e)
            return None

    def list_objects(self, bucket_name, frequency):
        """Fetch the list of objects found on the S3 bucket."""
        prefix = '{dp}/{freq}'.format(dp=self.deployment_prefix, freq=frequency)
        res = {'objects': []}

        try:
            for obj in self.s3.Bucket(bucket_name).objects.filter(Prefix=prefix):
                if os.path.basename(obj.key) != '':
                    res['objects'].append(obj.key)
        except ClientError as e:
            if e.response['Error']['Code'] == 'NoSuchKey':
                logger.exception('ERROR - No Such Key %s exists' % prefix)
            elif e.response['Error']['Code'] == 'NoSuchBucket':
                logger.exception('ERROR - No Such Bucket %s exists' % bucket_name)
            else:
                logger.exception('%r' % e)

        return res
