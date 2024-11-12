import time
import os
import boto3
import json
import re
import random  # For jitter
from uuid import uuid4

# Initialize AWS clients
s3_client = boto3.client('s3')
bedrock_client = boto3.client('bedrock-runtime', region_name='ap-south-1')

# Get the S3 bucket name from environment variables
bucket_name = os.getenv('S3_BUCKET')  # Ensure this is set in your Lambda environment

# Function to extract specific terms from document text
def extract_terms(text):
    patterns = {
        'supply_address': r'Supply Address:\s*([^\n]+)',
        'tariff_name': r'Tariff Name\s*([^\n]+)',
        'energy_used': r'Energy Used\s*([\d,\.]+)\s*kWh',
        'unit_rate': r'Unit Rate\s*([\d,\.]+)\s*p/kWh',
        'standing_charge': r'Standing Charge\s*([\d,\.]+)p/day',
        'subtotal_before_vat': r'Subtotal of charges before VAT\s*([\d,\.]+)',
        'vat': r'VAT @\s*([\d,\.]+)%',
        'total_charges': r'Total Electricity Charges\s*([\d,\.]+)'
    }
    return {key: re.search(pattern, text).group(1) if re.search(pattern, text) else None for key, pattern in patterns.items()}

def lambda_handler(event, context):
    file_key = event['Records'][0]['s3']['object']['key']
    
    try:
        # Read the document text from S3
        document_text = s3_client.get_object(Bucket=bucket_name, Key=file_key)['Body'].read().decode('utf-8')
    except s3_client.exceptions.NoSuchKey:
        print(f"File not found in S3: {file_key}")
        return {'statusCode': 404, 'body': f"File not found: {file_key}"}
    except Exception as e:
        print(f"Error reading file from S3: {str(e)}")
        return {'statusCode': 500, 'body': f"Error reading file: {str(e)}"}

    # Extract specific terms from the text
    extracted_terms = extract_terms(document_text)

    # Detailed prompt for better Bedrock model analysis
    prompt = (
        "Analyze the following electricity bill document text and identify key details such as supply address, "
        "tariff name, energy consumption, unit rate, standing charge, and total charges. Ensure the values are "
        "accurate and presented in a structured format. Additionally, provide insights about potential cost-saving "
        "opportunities if identifiable from the data."
    )

    request_body = {
        "inputText": document_text,
        "textGenerationConfig": {
            "maxTokenCount": 512,
            "stopSequences": [],
            "temperature": 0.7,  # Adjusted for balance between determinism and creativity
            "topP": 0.9
        },
        "prompt": prompt
    }

    max_retries = 5
    for attempt in range(max_retries):
        try:
            print(f"Sending request to Amazon Titan for file: {file_key}, Attempt: {attempt + 1}")
            response = bedrock_client.invoke_model(
                modelId="amazon.titan-text-lite-v1",
                body=json.dumps(request_body),
                contentType="application/json"
            )

            # Decode the response
            response_body = json.loads(response['body'].read().decode('utf-8'))

            # Final output including extracted terms and model response
            final_output = {
                "analysis": {
                    "bedrock_response": response_body,
                    "extracted_terms": extracted_terms
                }
            }

            # Save the result to S3 with a simple, descriptive file name
            sanitized_file_key = file_key.split('/')[-1].split('.')[0]
            output_key = f"{sanitized_file_key}_result.json"
            
            s3_client.put_object(
                Bucket=bucket_name,
                Key=output_key,
                Body=json.dumps(final_output)
            )

            return {'statusCode': 200, 'body': "Analysis complete and result saved to S3."}

        except bedrock_client.exceptions.ThrottlingException:
            if attempt < max_retries - 1:
                sleep_time = (2 ** attempt) + random.uniform(0, 1)  # Exponential backoff with jitter
                print(f"Throttling exception. Retrying in {sleep_time:.2f} seconds...")
                time.sleep(sleep_time)
            else:
                print("Max retries reached. Bedrock is currently overloaded.")
                return {'statusCode': 500, 'body': "Max retries reached. Bedrock is currently overloaded."}
        except Exception as e:
            print(f"Error invoking Bedrock model: {str(e)}")
            return {'statusCode': 500, 'body': f"Error invoking Bedrock model: {str(e)}"}







