# -*- coding: utf-8 -*-
"""
========================
AWS Lambda
========================
Contributor: Chirag Rathod (Srce Cde)
========================
"""
import sys
import traceback
import logging
import json
import boto3
from urllib.parse import unquote_plus

# Set up logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

def process_error() -> dict:
    ex_type, ex_value, ex_traceback = sys.exc_info()
    traceback_string = traceback.format_exception(ex_type, ex_value, ex_traceback)
    error_msg = json.dumps(
        {
            "errorType": ex_type.__name__,
            "errorMessage": str(ex_value),
            "stackTrace": traceback_string,
        }
    )
    return error_msg

def extract_text(response: dict, extract_by="LINE") -> list:
    text = []
    for block in response.get("Blocks", []):
        if block["BlockType"] == extract_by:
            text.append(block.get("Text", ""))
    return text

def lambda_handler(event, context):
    textract = boto3.client("textract")
    s3 = boto3.client("s3")

    try:
        if "Records" in event:
            file_obj = event["Records"][0]
            bucketname = file_obj["s3"]["bucket"].get("name")
            filename = unquote_plus(file_obj["s3"]["object"].get("key", ""))

            # Check if the file is in .jpg format
            if not filename.lower().endswith(".jpg"):
                logger.error("The file is not in .jpg format.")
                raise ValueError("The file is not in .jpg format.")

            logger.info(f"Bucket: {bucketname} ::: Key: {filename}")

            # Use Textract to analyze the document
            try:
                response = textract.detect_document_text(
                    Document={
                        "S3Object": {
                            "Bucket": bucketname,
                            "Name": filename,
                        }
                    }
                )
            except Exception as e:
                logger.error(f"Textract API call failed: {str(e)}")
                raise

            logger.info("Textract response: %s", json.dumps(response))

            # Extract text at the specified level (e.g., LINE or WORD)
            raw_text = extract_text(response, extract_by="LINE")
            logger.info("Extracted Text: %s", raw_text)

            # Generate the output file name without a unique identifier
            output_key = f"output/{filename.split('/')[-1].split('.')[0]}.txt"

            # Save the extracted text back to the same S3 bucket
            try:
                s3.put_object(
                    Bucket=bucketname,
                    Key=output_key,
                    Body="\n".join(raw_text),
                )
                logger.info(f"Text saved successfully to {output_key}")
            except Exception as e:
                logger.error(f"Failed to save extracted text to S3: {str(e)}")
                raise

            return {
                "statusCode": 200,
                "body": json.dumps("Document processed successfully!"),
            }
    except Exception:
        error_msg = process_error()
        logger.error(error_msg)

    return {"statusCode": 500, "body": json.dumps("Error processing the document!")}
