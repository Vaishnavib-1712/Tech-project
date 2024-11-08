import os
import boto3
from botocore.exceptions import ClientError
s3_client = boto3.client('s3')
bucket_name = os.getenv('S3_BUCKET')
def handler(event, context):
    try:
        response = s3_client.generate_presigned_url(
            'put_object',
            Params={'Bucket': bucket_name, 'Key': event['queryStringParameters']['file_name']},
            ExpiresIn=3600
        )
        return {
            'statusCode': 200,
            'body': response
        }
    except ClientError as e:
        return {
            'statusCode': 500,
            'body': f"Error generating presigned URL: {str(e)}"
        }
