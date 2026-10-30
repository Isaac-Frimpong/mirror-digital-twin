"""Optional Anthropic image analysis, with strict Twilio URL and size checks."""
import base64
import os
import re
from urllib.parse import urlsplit, urljoin
import requests

MAX_BYTES=4*1024*1024
VALID_IMAGE={'image/jpeg','image/png','image/gif','image/webp'}

def analyze_image(media_url, media_type, message_sid, question, language='en'):
    account=os.environ.get('TWILIO_ACCOUNT_SID','')
    auth=os.environ.get('TWILIO_AUTH_TOKEN','')
    key=os.environ.get('ANTHROPIC_API_KEY','')
    if not (account and auth and key): raise RuntimeError('Image analysis is not configured.')
    if media_type not in VALID_IMAGE: raise ValueError('Unsupported image format.')
    # Only a signed webhook's current message media URL under the configured account.
    pat=r'/2010-04-01/Accounts/'+re.escape(account)+r'/Messages/'+re.escape(message_sid)+r'/Media/ME[0-9a-fA-F]{32}'
    url=urlsplit(media_url)
    if url.scheme!='https' or url.netloc!='api.twilio.com' or not re.fullmatch(pat,url.path) or url.query or url.fragment:
        raise ValueError('Invalid media URL.')
    api_sid=os.environ.get('TWILIO_API_KEY_SID')
    api_secret=os.environ.get('TWILIO_API_KEY_SECRET')
    if bool(api_sid) != bool(api_secret): raise RuntimeError('Incomplete media API credentials.')
    sid,secret=(api_sid,api_secret) if api_sid else (account,auth)
    response=requests.get(media_url,auth=(sid,secret),stream=True,timeout=(5,15),allow_redirects=False)
    if response.status_code in (301,302,303,307,308):
        loc=urljoin(media_url,response.headers.get('Location','')); dest=urlsplit(loc)
        response.close()
        if dest.scheme!='https' or dest.netloc not in ('mms.twiliocdn.com','media.twiliocdn.com'):
            raise ValueError('Untrusted media redirect.')
        # Never send Twilio credentials to the CDN.
        response=requests.get(loc,stream=True,timeout=(5,15),allow_redirects=False)
    try:
        response.raise_for_status()
        body=bytearray()
        for part in response.iter_content(65536):
            body.extend(part)
            if len(body)>MAX_BYTES: raise ValueError('Image is too large.')
    finally: response.close()
    # Verify actual bytes, not only the sender-provided content type.
    from PIL import Image
    from io import BytesIO
    Image.MAX_IMAGE_PIXELS=20_000_000
    with Image.open(BytesIO(body)) as img:
        actual={'JPEG':'image/jpeg','PNG':'image/png','GIF':'image/gif','WEBP':'image/webp'}.get(img.format)
        if actual!=media_type: raise ValueError('Image type mismatch.')
        if img.width * img.height > 20_000_000: raise ValueError('Image dimensions too large.')
        img.verify()
    import anthropic
    client=anthropic.Anthropic(api_key=key,timeout=20.0,max_retries=0)
    prompt=('Answer briefly in Swahili.' if language=='sw' else 'Answer briefly in English.')+' Describe the image. Do not claim certainty about health or identity. '+(question[:300] if question else '')
    result=client.messages.create(model=os.environ.get('ANTHROPIC_MODEL','claude-sonnet-4-20250514'),max_tokens=300,
        messages=[{'role':'user','content':[{'type':'image','source':{'type':'base64','media_type':actual,'data':base64.b64encode(body).decode()}},{'type':'text','text':prompt}]}])
    answer=' '.join(block.text for block in result.content if block.type=='text').strip()
    if not answer: raise ValueError('No image description returned.')
    return answer[:1400]
