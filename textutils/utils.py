import ast
import re
import json

def parse_keypoints(keypoints_str: str) -> list:
    """
    Convert a string representation of a list into an actual list.
    Handles both ast.literal_eval-compatible strings and malformed strings.
    
    Args:
        keypoints_str (str): String representation of a list
        
    Returns:
        list: Parsed list of keypoints
    """
    try:
        # First attempt: Try using ast.literal_eval
        try:
            print(keypoints_str)
            print(type(keypoints_str))
            if type(keypoints_str) == list:
                return keypoints_str
            return ast.literal_eval(keypoints_str)
        except (ValueError, SyntaxError):
            pass
        
        # Second attempt: Clean the string and try ast.literal_eval again
        cleaned_str = keypoints_str.strip()
        if not (cleaned_str.startswith('[') and cleaned_str.endswith(']')):
            cleaned_str = f"[{cleaned_str}]"
        try:
            return ast.literal_eval(cleaned_str)
        except (ValueError, SyntaxError):
            pass
        
        # Third attempt: Manual parsing using regex
        # Match anything between single or double quotes
        pattern = r'[\'"]([^\'"]*)[\'"]'
        matches = re.findall(pattern, keypoints_str)
        if matches:
            return matches
        
        # Final attempt: Split by comma if everything else fails
        # Remove brackets and split
        cleaned_str = cleaned_str.strip('[]')
        items = [item.strip().strip('\'"') for item in cleaned_str.split(',')]
        return [item for item in items if item]
        
    except Exception as e:
        print(f"Error parsing keypoints: {str(e)}")
        return False

def robust_json_parser(response_text):
    """
    Parse and extract JSON data with improved handling of nested structures
    and malformed JSON.
    
    Args:
        response_text (str): The response text potentially containing JSON
    
    Returns:
        dict: Parsed JSON dictionary with 'summary' and 'keypoints',
              or None if parsing fails
    """
    response_text = response_text.strip()
    
    try:
        # First attempt: Try to find the second JSON object (the actual data)
        json_pattern = r'\{[^{]*"summary"[^}]+\}'
        matches = re.finditer(json_pattern, response_text, re.DOTALL)
        
        for match in matches:
            try:
                parsed_data = json.loads(match.group(0))
                if isinstance(parsed_data, dict):
                    if 'summary' in parsed_data and 'keypoints' in parsed_data:
                        return parsed_data
            except json.JSONDecodeError:
                continue
        
        # Second attempt: Try to parse the entire text for any valid JSON
        try:
            parsed_data = json.loads(response_text)
            if isinstance(parsed_data, dict):
                if 'summary' in parsed_data and 'keypoints' in parsed_data:
                    return parsed_data
        except json.JSONDecodeError:
            pass
        
        # Final attempt: Manual extraction
        summary_match = re.search(r'"summary"\s*:\s*"([^"]*)"', response_text)
        keypoints_match = re.findall(r'"keypoints"\s*:\s*\[(.*?)\]', response_text, re.DOTALL)
        
        if summary_match and keypoints_match:
            summary = summary_match.group(1)
            keypoints_str = keypoints_match[0]
            # Clean up the keypoints
            keypoints = [k.strip(' "\'') for k in re.findall(r'"([^"]*)"', keypoints_str)]
            return {
                "summary": summary,
                "keypoints": [k for k in keypoints if k]
            }
        
        raise ValueError("Unable to find valid summary and keypoints")
        
    except Exception as e:
        print(f"JSON parsing error: {str(e)}")
        return None
    
def fix_pydantic_validation(response_text):
    """
    Attempt to fix and validate the response for Pydantic model
    
    Args:
        response_text (str): The response text to be validated
    
    Returns:
        dict: Parsed and potentially fixed JSON
    """
    try:
        # First, attempt robust parsing
        parsed_json = robust_json_parser(response_text)
        
        # Validate basic structure
        if not isinstance(parsed_json, dict):
            raise ValueError("Invalid JSON structure")
        
        # Ensure required keys exist
        if 'summary' not in parsed_json or 'keypoints' not in parsed_json:
            raise ValueError("Missing required keys")
        
        # Validate summary
        if not isinstance(parsed_json['summary'], str) or len(parsed_json['summary']) < 50:
            raise ValueError("Invalid summary")
        
        # Validate keypoints
        if not isinstance(parsed_json['keypoints'], list):
            raise ValueError("Keypoints must be a list")
        
        # Ensure 4-5 keypoints
        parsed_json['keypoints'] = parsed_json['keypoints'][:5]
        
        return parsed_json
    
    except Exception as e:
        # Log the error or handle it as needed
        print(f"JSON parsing error: {str(e)}")
        return None