"""Mobile-first command interface sharing the web twin's core functions."""
import time
import re
from datetime import date
from collections import Counter
from utils.core import DAYS, PERIODS, make_event, predict_activity, answer_question, search_notes, looks_like_injection
from utils.whatsapp_store import fresh

SW_DAYS={'jumatatu':'Monday','jumanne':'Tuesday','jumatano':'Wednesday','alhamisi':'Thursday','ijumaa':'Friday','jumamosi':'Saturday','jumapili':'Sunday'}
SW_PERIODS={'asubuhi':'morning','mchana':'afternoon','jioni':'evening'}
SW_ACT={'kukimbia':'running','kutembea':'walking','kusoma':'reading','kuprogramu':'coding'}
EN_ACT={v:k for k,v in SW_ACT.items()}
MENU_EN=('MIRROR • Routine twin\n'
 'LOG 2026-10-03 | morning | running | 45 | felt good\n'
 'PREDICT Saturday | morning\nASK What notes mention running?\nSTATUS • CLEAR • LANGUAGE SW\n'
 'Only what you report is known. Data expires after 24h of inactivity and can be lost sooner. In memory mode, expired data is removed on a later request.')
MENU_SW=('MIRROR • Pacha wa ratiba\n'
 'REKODI 2026-10-03 | asubuhi | kukimbia | 45 | nilifurahi\n'
 'TABIRI jumamosi | asubuhi\nULIZA neno kutoka kwenye maelezo\nHALI • FUTA • LANGUAGE EN\n'
 'Tunajua tu unachoripoti. Data huisha baada ya saa 24 bila matumizi; kumbukumbu husafishwa ombi linalofuata, au mapema zaidi.')

def loc(state,en,sw): return sw if state.get('language')=='sw' else en

def on_message(state, text, sid, media=None):
    text=' '.join(text.strip().split())[:2000]
    upper=text.upper()
    if upper in ('LANGUAGE SW','LUGHA SW'):
        state['language']='sw'
        return 'Lugha ni Kiswahili. Tuma HELP kwa maelekezo.'
    if upper in ('LANGUAGE EN','LUGHA EN'):
        state['language']='en'
        return 'Language set to English. Send HELP for instructions.'
    if not state['consented']:
        if upper in ('AGREE','KUBALI'):
            state['consented']=True
            return loc(state,'Thanks. You control what you share. Send HELP for commands. Data is temporary.', 'Asante. Unachagua unachoshiriki. Tuma HELP kwa maelekezo. Data ni ya muda.')
        return loc(state,
            'Welcome to MIRROR. This demo stores your number-linked routine entries temporarily; WhatsApp/Twilio process your messages. Do not send sensitive data. Reply AGREE to use it, or LANGUAGE SW for Kiswahili.',
            'Karibu MIRROR. Jaribio huhifadhi data yako kwa muda ikihusishwa na nambari yako; WhatsApp/Twilio huchakata ujumbe. Usitume data nyeti. Jibu KUBALI kuendelea.')
    if upper in ('HELP','MENU','MSAADA','HI','HELLO','HABARI','1'):
        return loc(state,MENU_EN,MENU_SW)
    if upper in ('CLEAR','FUTA'):
        lang=state['language']; state.clear(); state.update(fresh()); state['language']=lang
        return loc(state,'Your routine data and consent were cleared. Reply AGREE to start again.', 'Data yako na ridhaa vimefutwa. Jibu KUBALI kuanza tena.')
    if upper in ('IMAGE ON','PICHA NDIO') and state.get('channel')=='meta':
        return loc(state,'Image analysis is not available on the Meta connection yet.', 'Uchambuzi wa picha haupatikani kwenye muunganisho wa Meta bado.')
    if upper in ('IMAGE ON','PICHA NDIO'):
        state['image_consent']=True
        return loc(state,'Image consent enabled. Images you send may be sent to Anthropic for analysis. Send IMAGE OFF to revoke. The feature also requires an Anthropic API key.', 'Ridhaa ya picha imewashwa. Picha zinaweza kutumwa Anthropic kwa uchambuzi. Tuma PICHA HAPANA kusitisha. Ufunguo wa API unahitajika.')
    if upper in ('IMAGE OFF','PICHA HAPANA'):
        state['image_consent']=False
        return loc(state,'Image consent disabled.', 'Ridhaa ya picha imezimwa.')
    if looks_like_injection(text):
        return loc(state,'I can help with your own routine, but cannot follow instructions to reveal secrets.', 'Ninaweza kusaidia kuhusu ratiba yako, lakini siwezi kufichua siri.')
    if media:
        typ=media.get('type','')
        if typ=='meta_unsupported':
            return loc(state,'Media analysis is not available on the Meta connection yet. Please send a text command.', 'Uchambuzi wa faili haupatikani kwenye muunganisho wa Meta bado. Tafadhali tuma ujumbe wa maandishi.')
        if typ.startswith('image/'):
            if not state['image_consent']:
                return loc(state,'Image analysis is optional. To consent to sending images to Anthropic, send IMAGE ON, then resend the image. Do not send sensitive images.', 'Uchambuzi wa picha ni hiari. Tuma PICHA NDIO kukubali kutuma picha Anthropic, kisha tuma picha tena. Usitume picha nyeti.')
            return '__IMAGE__'
        return loc(state,'I can receive your file, but audio and documents are not analyzed in this prototype.', 'Nimepokea faili, lakini sauti na hati hazichambuliwi kwenye jaribio hili.')
    if upper in ('STATUS','HALI','2'):
        events=state['events']; counts=Counter(e['activity'] for e in events)
        summary=', '.join(f'{EN_ACT.get(k,k) if state["language"]=="sw" else k}: {v}' for k,v in counts.most_common(5)) or '—'
        return loc(state,f'{len(events)} reported activities. Counts: {summary}.',f'Shughuli {len(events)} zilizoripotiwa. Jumla: {summary}.')
    cmd, _, body=text.partition(' ')
    command=cmd.upper()
    if command in ('LOG','REKODI'):
        parts=[p.strip() for p in body.split('|')]
        if len(parts) not in (4,5):
            return loc(state,'Format: LOG YYYY-MM-DD | morning | activity | minutes | optional note', 'Muundo: REKODI YYYY-MM-DD | asubuhi | shughuli | dakika | maelezo hiari')
        if len(state['events'])>=100:
            return loc(state,'Session limit reached (100). Send CLEAR to start over.', 'Umefikia kikomo cha 100. Tuma FUTA kuanza upya.')
        day,period,activity,minutes=parts[:4]; period=SW_PERIODS.get(period.lower(),period.lower()); activity=SW_ACT.get(activity.lower(),activity.lower())
        try:
            if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',day): raise ValueError()
            if not re.fullmatch(r'\d{1,4}',minutes): raise ValueError()
            item=make_event(sid[-12:],date.fromisoformat(day),period,activity,int(minutes),parts[4] if len(parts)==5 else '')
            state['events'].append(item)
            return loc(state,f"Saved: {item['activity']} on {item['date']}, {item['time_period']}, {item['duration_minutes']} min.", f"Imehifadhiwa: {EN_ACT.get(item['activity'],item['activity'])}, {item['date']}, dakika {item['duration_minutes']}.")
        except (ValueError,OverflowError):
            return loc(state,'Could not save. Check the date, period, activity and minutes (0–1440). Send HELP.', 'Haijahifadhiwa. Angalia tarehe, muda, shughuli na dakika (0–1440). Tuma HELP.')
    if command in ('PREDICT','TABIRI'):
        parts=[p.strip().lower() for p in body.split('|')]
        if len(parts)!=2: return loc(state,'Format: PREDICT Saturday | morning', 'Muundo: TABIRI jumamosi | asubuhi')
        d=SW_DAYS.get(parts[0],parts[0].title()); p=SW_PERIODS.get(parts[1],parts[1])
        if d not in DAYS or p not in PERIODS: return loc(state,'Use a weekday and morning, afternoon or evening.', 'Tumia siku na asubuhi, mchana au jioni.')
        result=predict_activity(state['events'],d,p); n=result['sample_size']
        if not n: return loc(state,'No matching reports yet.', 'Hakuna rekodi zinazolingana bado.')
        lines=[f"{EN_ACT.get(x['activity'],x['activity']) if state['language']=='sw' else x['activity']}: {x['count']}/{n} ({x['proportion']:.0%})" for x in result['distribution']]
        msg=loc(state,f'{n} past reports:',f'Rekodi {n} zilizopita:')+'\n'+'\n'.join(lines)
        return msg+'\n'+loc(state,'Past reports only, not a guarantee.' if result['sufficient'] else 'Fewer than 5 reports: insufficient history for a prediction.', 'Ni rekodi za zamani tu, si uhakika.' if result['sufficient'] else 'Rekodi chini ya 5: hazitoshi kwa utabiri.')
    if command in ('ASK','ULIZA'):
        if not body: return loc(state,'Add a question after ASK.', 'Andika swali baada ya ULIZA.')
        if state['language']=='sw':
            found=search_notes(state['events'],body)
            if not found: return 'Sikupata maelezo yanayolingana. Jaribu neno ulilotumia kwenye rekodi.'
            return 'Maelezo yanayolingana:\n'+'\n'.join(f"{x['date']}: {x['text'][:250]}" for x in found)
        return answer_question(body,state['events'])['answer'][:1400]
    return loc(state,'I didn’t understand. Send HELP for commands.', 'Sikuelewa. Tuma HELP kwa maelekezo.')

def process_once(state, text, sid, media=None, image_fn=None):
    """Idempotency + per-sender rate limit, called inside a store transaction."""
    if sid in state['seen']: return state['seen'][sid]
    now=time.time(); state['rate']=[t for t in state['rate'] if t>now-60]
    if len(state['rate'])>=10: reply=loc(state,'Too many messages. Please try again in a minute.', 'Ujumbe mwingi. Tafadhali jaribu tena baada ya dakika moja.')
    else:
        state['rate'].append(now)
        reply=on_message(state,text,sid,media)
        if reply=='__IMAGE__':
            try:
                if image_fn is None: raise RuntimeError('Not configured')
                reply=image_fn(media['url'],media['type'],sid,text,state['language'])
            except Exception:
                reply=loc(state,'Image analysis is unavailable. Check setup or try a smaller supported image.', 'Uchambuzi wa picha haupatikani. Angalia usanidi au jaribu picha ndogo inayokubalika.')
    state['seen'][sid]=reply
    while len(state['seen'])>40: del state['seen'][next(iter(state['seen']))]
    return reply
