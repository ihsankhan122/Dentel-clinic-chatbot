import pandas as pd
import google.generativeai as genai
import re
from langdetect import detect, DetectorFactory
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DetectorFactory.seed = 0  # to make language detection consistent

# 🔑 Gemini API key
GEMINI_API_KEY = "AIzaSyDXB538kTAfi6dILexYffuoXrmEhXl8hqc"
genai.configure(api_key=GEMINI_API_KEY)

# 📦 Load Gemini model
model = genai.GenerativeModel("gemini-2.5-flash")

# ✅ Urdu/Roman Urdu detection
def is_urdu(text):
    try:
        lang = detect(text)
    except:
        lang = ""
    urdu_chars = re.findall(r'[\u0600-\u06FF]', text)
    has_urdu_script = len(urdu_chars) > 5
    is_probably_roman_urdu = lang in ["ur", "hi", "fa"]
    return has_urdu_script or is_probably_roman_urdu

# ✅ Format Gemini response to look clean
def format_response(response_text: str) -> str:
    logger.info(f"Formatting response: {response_text[:100]}...")
    
    # If response is empty, return a default message
    if not response_text or response_text.strip() == "":
        logger.warning("Empty response received from Gemini")
        return "I'm sorry, I couldn't generate a response. Please try again."
    
    # Remove code blocks
    response_text = re.sub(r'```python.*?```', '', response_text, flags=re.DOTALL)
    response_text = re.sub(r'```.*?```', '', response_text, flags=re.DOTALL)
    
    # Split response into records based on patient or MRN pattern
    records = re.split(r'(?=\*\*(?:Patient|MRN)\*\*:)', response_text)
    formatted_records = []
    
    for record in records:
        if not record.strip():
            continue
            
        # Clean up the record
        record = record.strip()
        
        # Remove any leading dashes
        record = re.sub(r'^-+\s*', '', record)
        
        # Extract all field-value pairs
        field_pattern = r'(\*\*[^*]+\*\*:\s*[^\n]+)'
        fields = re.findall(field_pattern, record)
        
        if not fields:
            # If no fields found, treat as a general message
            formatted_records.append(record)
            continue
            
        # Start the record with a dash
        formatted_record = "- "
        
        # Process each field
        for i, field in enumerate(fields):
            # Clean up the field
            field = re.sub(r'-+\s*', '', field.strip())
            
            # Add the field to the record
            if i == 0:
                # First field goes on the same line as the dash
                formatted_record += field
            else:
                # Subsequent fields are indented
                formatted_record += f"\n  {field}"
        
        formatted_records.append(formatted_record)
    
    # Join records with double newlines
    result = '\n\n'.join(formatted_records).strip()
    
    # If after formatting the result is empty, return the original response
    if not result:
        logger.warning("Formatted result is empty, returning original response")
        return response_text
    
    logger.info(f"Formatted result: {result[:100]}...")
    return result

# ✅ Get response from Gemini - UPDATED TO INCLUDE SESSION HISTORY
def get_chat_response(user_message, df, session_history=None):
    try:
        logger.info(f"Processing user message: {user_message}")
        
        # Limit to first 500 rows to stay within Gemini token quota
        df_sample = df.head(500)
        columns = df_sample.columns.tolist()
        row_count = len(df_sample)
        data_preview = df_sample.to_dict(orient='records')
        urdu_requested = is_urdu(user_message)
        language_instruction = (
            "جواب صرف اردو میں دیں۔ انگریزی استعمال نہ کریں۔\n\n" if urdu_requested else ""
        )
        
        # Format session history for the prompt
        history_text = ""
        if session_history:
            history_text = "\n\nRECENT CHAT HISTORY:\n"
            for i, (user_msg, bot_resp) in enumerate(session_history[-5:]):
                # Truncate long messages to avoid exceeding token limit
                user_msg = user_msg[:200] + "..." if len(user_msg) > 200 else user_msg
                bot_resp = bot_resp[:200] + "..." if len(bot_resp) > 200 else bot_resp
                history_text += f"User: {user_msg}\nBot: {bot_resp}\n\n"
        
        prompt = f"""
You are a dental clinic data assistant with memory of recent conversations. A user has uploaded a dataset containing dental clinic records.
🔢 The dataset contains {row_count} rows (showing first 500 rows).
📊 The available columns are: {columns}
Here is a sample of the dataset (first 500 rows only) as JSON records:
{data_preview}
{history_text}
📄 Format your response as a clean, readable list with proper formatting.
📌 Answer the user's question based strictly on the data above.
✅ Be accurate with numbers (e.g., patient count, revenue, invoices, appointments).
🦷 Provide answers related to patients, treatments, invoices, payments, doctors, and appointments if asked.
💬 If the user asks general questions (e.g., "how are you?"), respond politely and stay helpful.
🚫 If any info is missing in the dataset, clearly say it's not available.
💭 Use the recent chat history to provide context-aware responses. Remember details from previous conversations.

RESPONSE FORMATTING INSTRUCTIONS:
1. For data records, use this exact format:
   - **Patient**: [Name]
     **MRN**: [Number]
     **Registration date**: [Date]
     **City**: [City]
     **Invoice number**: [Number]
     **Invoice date**: [Date]
     **Description**: [Description]
     **Price**: [Amount]
     **Doctor**: [Name]

2. For general questions, respond in a friendly, conversational tone.

3. For lists of items, use bullet points:
   - Item 1
   - Item 2
   - Item 3

4. Always use proper markdown formatting for field names: **Field Name**: Value

IMPORTANT: Always provide a meaningful response. Never return an empty message.

{language_instruction}
User's Question: "{user_message}"
"""
        logger.info(f"Sending prompt to Gemini: {prompt[:200]}...")
        response = model.generate_content(prompt)
        logger.info(f"Received response from Gemini: {response.text[:100]}...")
        
        formatted_response = format_response(response.text)
        logger.info(f"Formatted response: {formatted_response[:100]}...")
        
        return formatted_response
    except Exception as e:
        logger.error(f"Error in get_chat_response: {str(e)}")
        return f"Error generating response: {str(e)}"