import time
import os
import boto3
import json
import re
import uuid
import random  # For jitter

# Initialize the S3 and Bedrock clients
s3_client = boto3.client('s3')
bedrock_client = boto3.client('bedrock-runtime', region_name='ap-south-1')

# Get the bucket name from environment variable
bucket_name = os.getenv('S3_BUCKET')  # Set S3_BUCKET environment variable in Lambda

# Function to extract specific terms from the document text
def extract_terms(text):
    terms = {
        'supply_address': re.search(r'Supply Address:\s*([^\n]+)', text),
        'tariff_name': re.search(r'Tariff Name\s*([^\n]+)', text),
        'energy_used': re.search(r'Energy Used\s*([\d,\.]+)\s*kWh', text),
        'unit_rate': re.search(r'Unit Rate\s*([\d,\.]+)\s*p/kWh', text),
        'standing_charge': re.search(r'Standing Charge\s*([\d,\.]+)p/day', text),
        'subtotal_before_vat': re.search(r'Subtotal of charges before VAT\s*([\d,\.]+)', text),
        'vat': re.search(r'VAT @\s*([\d,\.]+)%', text),
        'total_charges': re.search(r'Total Electricity Charges\s*([\d,\.]+)', text)
    }
    # Return extracted terms as a dictionary
    return {key: match.group(1) if match else None for key, match in terms.items()}

def lambda_handler(event, context):
    # Extract the file key from the event and read the document
    file_key = event['Records'][0]['s3']['object']['key']
    
    try:
        # Get the document text from S3
        document_text = s3_client.get_object(Bucket=bucket_name, Key=file_key)['Body'].read().decode('utf-8')
    except s3_client.exceptions.NoSuchKey as e:
        print(f"File not found in S3: {file_key}")
        return {
            'statusCode': 404,
            'body': json.dumps(f"File not found: {file_key}")
        }
    except Exception as e:
        print(f"Error reading file from S3: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps(f"Error reading file: {str(e)}")
        }

    # Extract specific terms like supply address, tariff name, etc.
    extracted_terms = extract_terms(document_text)

    # **Prompt**: This is the instruction you give to the model
    prompt = f"""
    You are a document analysis assistant. Please extract the following details from the given document:

    - Supply Address: [Extract the supply address]
    - Tariff Name: [Extract the tariff name]
    - Energy Used (in kWh): [Extract the energy used]
    - Unit Rate (p/kWh): [Extract the unit rate]
    - Standing Charge (p/day): [Extract the standing charge]
    - Subtotal before VAT: [Extract the subtotal before VAT]
    - VAT Percentage: [Extract the VAT percentage]
    - Total Charges: [Extract the total charges]

    Document Text:
    {document_text}
    """

    # Prepare request body for Bedrock model (use the prompt as content)
    model_id = "anthropic.claude-3-sonnet-20240229-v1:0"  # Replace with your correct model ID
    request_body = {
        "messages": [
            {
                "role": "user",
                "content": prompt  # Pass the prompt as the content for the model
            }
        ],
        "anthropic_version": "bedrock-2023-05-31",  # Ensure this version is correct
        "max_tokens": 2000,
        "temperature": 1,
        "top_k": 250,
        "top_p": 0.999,
        "stop_sequences": ["\\n\\nHuman:"]
    }

    max_retries = 5
    for attempt in range(max_retries):
        try:
            # Invoke Bedrock model
            print(f"Sending request to Bedrock for file: {file_key}, Attempt: {attempt + 1}")
            response = bedrock_client.invoke_model(
                modelId=model_id,
                body=json.dumps(request_body),  # Send JSON as body
                contentType="application/json"
            )
            
            # Read and decode the response body
            response_body = response['body'].read().decode('utf-8')
            result = json.loads(response_body)

            # Prepare the final output including the extracted terms and analysis result
            final_output = {
                "analysis": {
                    "bedrock_response": result,
                    "extracted_terms": extracted_terms
                }
            }

            # Create a sanitized key for saving the result to S3
            sanitized_file_key = file_key.split('/')[-1].split('.')[0]
            output_key = f"processed_result_{sanitized_file_key}_{uuid.uuid4().hex}.json"
            
            # Save the final output to S3
            s3_client.put_object(
                Bucket=bucket_name,
                Key=output_key,
                Body=json.dumps(final_output)
            )

            return {
                'statusCode': 200,
                'body': "Analysis complete and result saved to S3."
            }

        except bedrock_client.exceptions.ThrottlingException as e:
            # Exponential backoff with jitter
            if attempt < max_retries - 1:
                sleep_time = (2 ** attempt) + (0.1 * attempt)  # Exponential backoff with jitter
                jitter = random.uniform(0, 1)  # Adding random jitter
                sleep_time += jitter  # Apply jitter
                print(f"Throttling exception. Retrying in {sleep_time:.2f} seconds...")
                time.sleep(sleep_time)
            else:
                print("Max retries reached. Bedrock is currently overloaded.")
                return {
                    'statusCode': 500,
                    'body': json.dumps("Max retries reached. Bedrock is currently overloaded.")
                }
        except Exception as e:
            # Handle any other errors
            print(f"Error invoking Bedrock model: {str(e)}")
            return {
                'statusCode': 500,
                'body': json.dumps(f"Error invoking Bedrock model: {str(e)}")
            }
