import json
import os
import uuid
from collections import Counter
from datetime import date
from html import escape
from pathlib import Path

import pandas as pd
import streamlit as st
from utils.core import (DAYS, PERIODS, make_event, predict_activity, answer_question,
                        looks_like_injection, has_pii, normalize)
from utils.llm import enhance_answer
from utils.whatsapp_store import fresh
from utils.whatsapp_logic import process_once

st.set_page_config(page_title='MIRROR | Your routine twin', page_icon='◒', layout='wide', initial_sidebar_state='expanded')
ROOT = Path(__file__).parent

st.markdown('''<style>
.stApp {background: #f8f9f4; color:#1b2923;}
[data-testid="stSidebar"] {background: #eaf0e5; border-right:1px solid #dce4d9;}
[data-testid="stSidebar"] .block-container {padding-top:2rem;}
.block-container {max-width: 1420px; padding-top: 2.2rem; padding-bottom: 5rem;}
#MainMenu {visibility:hidden;} footer {visibility:hidden;}
h1,h2,h3 {letter-spacing:-0.045em !important; color:#192c23 !important;}
.hero-eyebrow {font-size:11px; font-weight:800; letter-spacing:.16em; text-transform:uppercase; color:#668273; margin-bottom:11px;}
.hero-title {font-size: clamp(38px,4.2vw,59px); font-weight:750; letter-spacing:-.065em; line-height:1.02; color:#1b3026; margin:0 0 14px;}
.hero-sub {font-size:16px; line-height:1.6; color:#6d7c70; max-width:600px; margin-bottom:25px;}
.brand {font-size:23px; font-weight:850; letter-spacing:-.055em; color:#193127; margin-bottom:0;}
.brand-mark {display:inline-flex; width:32px; height:32px; border-radius:10px; background:#1b3b2a; color:#c9f7a0; align-items:center; justify-content:center; font-size:20px; margin-right:9px;}
.brand-caption {color:#718574; font-size:10px; letter-spacing:.14em; font-weight:700; margin:5px 0 28px 42px; text-transform:uppercase;}
.sidebar-label {color:#6e8271; font-size:10px; font-weight:800; letter-spacing:.14em; text-transform:uppercase; margin:25px 0 8px;}
.profile-card {border-radius:14px; background:#dbe9d5; padding:16px; margin:4px 0 16px;}
.profile-icon {display:inline-flex; width:36px; height:36px; border-radius:50%; align-items:center; justify-content:center; background:#244b34; color:#d6f8be; font-weight:700; margin-right:9px;}
.metric-card {background:white; border:1px solid #e3eae0; border-radius:16px; padding:20px 21px; min-height:134px;}
.metric-top {display:flex; justify-content:space-between; align-items:center; color:#6c7f70; font-size:12px; font-weight:650;}
.metric-icon {color:#41654b; background:#eaf4e5; border-radius:9px; padding:5px 8px; font-size:14px;}
.metric-value {font-size:31px; line-height:1.05; font-weight:750; letter-spacing:-.055em; margin:13px 0 5px; color:#1e3929;}
.metric-foot {font-size:11px; color:#8b9b8d;}
.section-kicker {font-size:10px; text-transform:uppercase; color:#8a9d8b; letter-spacing:.15em; font-weight:800; margin:10px 0 5px;}
.section-title {font-size:23px; font-weight:750; letter-spacing:-.045em; color:#20382a; margin-bottom:3px;}
.section-desc {font-size:13px; color:#819184; margin-bottom:17px;}
.banner {background:#203f2e; color:#edf9e9; padding:22px 24px; border-radius:17px; margin-bottom:20px;}
.banner .small {font-size:10px; color:#b4d99d; text-transform:uppercase; letter-spacing:.15em; font-weight:800;}
.banner .title {font-size:21px; font-weight:700; letter-spacing:-.04em; margin:8px 0 4px;}
.banner .sub {font-size:13px; line-height:1.5; color:#c0d4c1;}
.event-row {display:flex; align-items:center; gap:13px; border-bottom:1px solid #edf1eb; padding:13px 0;}
.event-dot {width:38px; height:38px; border-radius:12px; display:flex; align-items:center; justify-content:center; background:#edf5e8; color:#456f4c; font-size:17px; flex-shrink:0;}
.event-name {font-size:14px; font-weight:700; color:#253d2e; text-transform:capitalize;}
.event-meta {font-size:11px; color:#90a093; margin-top:3px;}
.event-duration {margin-left:auto; font-size:12px; color:#6f8272; white-space:nowrap;}
.chip {font-size:10px; color:#46674c; background:#e8f3e2; border-radius:99px; padding:5px 9px; font-weight:700; white-space:nowrap;}
.status {display:inline-block; color:#48664e; background:#e8f1e3; border:1px solid #dcebd5; border-radius:99px; padding:6px 10px; font-size:11px; font-weight:700;}
.note-card {border-left:3px solid #9bc97f; padding:10px 14px; background:#f0f6ec; border-radius:0 10px 10px 0; color:#57715d; font-size:12px; line-height:1.55;}
[data-testid="stTabs"] [data-baseweb="tab-list"] {gap:26px; border-bottom:1px solid #dce5da;}
[data-testid="stTabs"] [data-baseweb="tab"] {height:52px; background:none; padding:0 3px; font-weight:650; color:#7c8d7e;}
[data-testid="stTabs"] [aria-selected="true"] {color:#20422e !important;}
[data-testid="stButton"] button[kind="primary"], [data-testid="stFormSubmitButton"] button[kind="primary"] {background:#244b34; border:1px solid #244b34; color:white; border-radius:10px; font-weight:650;}
[data-testid="stButton"] button, [data-testid="stFormSubmitButton"] button {border-radius:10px;}
[data-testid="stVerticalBlockBorderWrapper"] > div {border-color:#e0e9dd; border-radius:16px; background:#fff;}
[data-testid="stDataFrame"] {border-radius:10px;}
</style>''', unsafe_allow_html=True)

def seed_data():
    raw=json.loads((ROOT/'data'/'knowledge_base.json').read_text())
    return [make_event(f'sample-{i+1:03d}',date.fromisoformat(x['date']),x['time_period'],x['activity'],x['duration_minutes'],x['note']) for i,x in enumerate(raw)]

def init():
    defaults={'events':seed_data(), 'sample_mode':True, 'profile_name':'Alex', 'profile_goal':'Build a more mindful routine', 'chat_history':[]}
    for k,v in defaults.items():
        if k not in st.session_state: st.session_state[k]=v
init()

def section(kicker,title,description=''):
    st.markdown(f'<div class="section-kicker">{escape(kicker)}</div><div class="section-title">{escape(title)}</div><div class="section-desc">{escape(description)}</div>',unsafe_allow_html=True)

def metric(label,value,foot,icon):
    st.markdown(f'<div class="metric-card"><div class="metric-top"><span>{escape(label)}</span><span class="metric-icon">{icon}</span></div><div class="metric-value">{escape(str(value))}</div><div class="metric-foot">{escape(foot)}</div></div>',unsafe_allow_html=True)

def event_row(e):
    st.markdown(f'''<div class="event-row"><div class="event-dot">◒</div><div><div class="event-name">{escape(e['activity'])}</div><div class="event-meta">{escape(e['day_of_week'])} · {escape(e['date'])} · {escape(e['time_period'].title())}</div></div><div class="event-duration">{e['duration_minutes']} min</div></div>''',unsafe_allow_html=True)

with st.sidebar:
    st.markdown('<div class="brand"><span class="brand-mark">◒</span>MIRROR<span style="color:#8aa38c">.</span></div><div class="brand-caption">Your personal digital twin</div>',unsafe_allow_html=True)
    st.markdown('<div class="sidebar-label">YOUR SPACE</div>',unsafe_allow_html=True)
    initial=escape((st.session_state.profile_name or 'Y')[0].upper())
    st.markdown(f'<div class="profile-card"><span class="profile-icon">{initial}</span><span style="font-weight:750;color:#24432d">{escape(st.session_state.profile_name or "Your profile")}</span><div style="font-size:11px;color:#6d8770;margin-top:10px">{escape(st.session_state.profile_goal or "No goal set yet")}</div></div>',unsafe_allow_html=True)
    with st.expander('✎  Edit profile'):
        with st.form('profile_form'):
            name=st.text_input('Display name',value=st.session_state.profile_name,max_chars=40)
            goal=st.text_input('Personal goal',value=st.session_state.profile_goal,max_chars=120)
            if st.form_submit_button('Save profile', type='primary'):
                st.session_state.profile_name=normalize(name) or 'You'
                st.session_state.profile_goal=normalize(goal)
                st.session_state.chat_history=[]
                st.rerun()
    st.markdown('<div class="sidebar-label">SESSION STATUS</div>',unsafe_allow_html=True)
    st.markdown('<span class="status">● &nbsp;Sample data loaded</span>' if st.session_state.sample_mode else '<span class="status">● &nbsp;Your current session</span>',unsafe_allow_html=True)
    st.caption('Sample records are fictional. Your session is temporary and may be lost when you close or reconnect.')
    if st.button('Start with a blank twin',use_container_width=True):
        st.session_state.events=[]; st.session_state.chat_history=[]; st.session_state.sample_mode=False
        st.session_state.profile_name='You'; st.session_state.profile_goal=''
        st.rerun()
    if st.button('Reload sample data',use_container_width=True):
        st.session_state.events=seed_data(); st.session_state.chat_history=[]; st.session_state.sample_mode=True
        st.session_state.profile_name='Alex'; st.session_state.profile_goal='Build a more mindful routine'
        st.rerun()
    st.markdown('<div class="sidebar-label">BUILT WITH CARE</div>',unsafe_allow_html=True)
    st.markdown('<div class="note-card">Your twin learns only from what you share. It doesn’t track you, observe you, or control your activities.</div>',unsafe_allow_html=True)
    with st.expander('Privacy & optional AI'):
        st.write('Everything is held in this app session, not in durable personal storage. Do not enter sensitive information in a public demo. Pattern-based privacy and injection checks are imperfect.')
        st.write('If you enable Groq, your question and the selected evidence are sent to Groq. Leave it off to use the deterministic, local answer mode.')

name=escape(st.session_state.profile_name or 'you')
st.markdown(f'<div class="hero-eyebrow">YOUR SPACE &nbsp; / &nbsp; PERSONAL DIGITAL TWIN</div><div class="hero-title">A little more insight,<br>a little more you<span style="color:#8dbb79">.</span></div><div class="hero-sub">A thoughtful reflection of your routines, built from the moments you choose to share.</div>',unsafe_allow_html=True)

if st.session_state.sample_mode:
    st.info('You’re exploring fictional sample data for Alex. Select **Start with a blank twin** in the sidebar to enter your own.', icon='✳')
else:
    st.caption('Your entries are temporary for this session. Avoid sensitive personal information.')

events=st.session_state.events
counts=Counter(e['activity'] for e in events)
common=counts.most_common(1)[0][0].title() if counts else '—'
minutes=sum(e['duration_minutes'] for e in events)
cols=st.columns(4)
with cols[0]: metric('Activities logged',len(events),'Moments in your twin','◒')
with cols[1]: metric('Most frequent',common, f'{max(counts.values())} reports' if counts else 'No activities yet','✳')
with cols[2]: metric('Time recorded',f'{minutes//60}h {minutes%60:02d}m','Across reported activities','◷')
with cols[3]: metric('Twin status','Active' if events else 'Ready','Session-only memory','↗')
st.write('')
overview, logtab, chat, scenario, mobile = st.tabs(['Overview', 'Activity log', 'Ask your twin', 'What-if studio', 'WhatsApp preview'])

with overview:
    st.write('')
    left,right=st.columns([1.65,1],gap='large')
    with left:
        section('THE BIG PICTURE','Your activity landscape','A snapshot of the routines you’ve reported.')
        with st.container(border=True):
            if counts:
                df=pd.DataFrame([{'Activity':a.title(),'Reports':c} for a,c in counts.most_common()]).set_index('Activity')
                st.bar_chart(df, color='#9dce87', height=260)
                st.caption('Counts reflect reported activities in this session, not automatic tracking.')
            else:
                st.info('Add an activity in the Activity log to see your landscape.')
        st.write('')
        section('YOUR STORY','Recent moments','The latest entries in your routine.')
        with st.container(border=True):
            recent=sorted(events,key=lambda e:e['date'],reverse=True)[:4]
            if recent:
                for e in recent: event_row(e)
            else: st.write('No activities yet. Start by adding your first moment.')
    with right:
        st.markdown('<div class="banner"><div class="small">✳ &nbsp; YOUR TWIN, YOUR PACE</div><div class="title">Small moments,<br>meaningful patterns.</div><div class="sub">Every entry helps build a clearer picture of the routines that matter to you.</div></div>',unsafe_allow_html=True)
        section('A PLACE TO BEGIN','Get to know your twin','Explore the different ways to use your space.')
        with st.container(border=True):
            st.markdown('**01 &nbsp; Log a moment**  \n<span style="color:#829185;font-size:12px">Add an activity, a duration and a note.</span>',unsafe_allow_html=True)
            st.divider()
            st.markdown('**02 &nbsp; Ask a question**  \n<span style="color:#829185;font-size:12px">Find relevant notes and past patterns.</span>',unsafe_allow_html=True)
            st.divider()
            st.markdown('**03 &nbsp; Explore a what-if**  \n<span style="color:#829185;font-size:12px">See a distribution of past reports.</span>',unsafe_allow_html=True)
        st.write('')
        st.markdown('<div class="note-card"><b>A note on predictions</b><br>Estimates describe your reported history. They are not guarantees or real-time observations.</div>',unsafe_allow_html=True)

with logtab:
    st.write('')
    a,b=st.columns([1,1.45],gap='large')
    with a:
        section('ADD TO YOUR STORY','Log a moment','Tell your twin about an activity you did.')
        with st.container(border=True):
            with st.form('add_event',clear_on_submit=True):
                d=st.date_input('Date',value=date.today())
                period=st.selectbox('Time of day',PERIODS,format_func=str.title)
                activity=st.text_input('Activity',placeholder='e.g. running, reading, cooking',max_chars=60)
                duration=st.number_input('Duration (minutes)',min_value=0,max_value=1440,value=30,step=5)
                note=st.text_area('Note (optional)',placeholder='What would you like to remember?',max_chars=2000)
                submitted=st.form_submit_button('＋  Add activity',type='primary',use_container_width=True)
                if submitted:
                    try:
                        e=make_event(uuid.uuid4().hex[:10],d,period,activity,duration,note)
                        st.session_state.events.append(e)
                        st.session_state.chat_history=[]
                        st.success('Activity added to this session.')
                        st.rerun()
                    except ValueError as exc: st.error(str(exc))
    with b:
        section('YOUR HISTORY','Activity log',f'{len(events)} reported activities in this session.')
        if events:
            rows=sorted(events,key=lambda e:e['date'],reverse=True)
            table=pd.DataFrame([{'Date':e['date'],'Day':e['day_of_week'],'Period':e['time_period'].title(),'Activity':e['activity'].title(),'Minutes':e['duration_minutes']} for e in rows])
            st.dataframe(table,hide_index=True,use_container_width=True)
            options={e['event_id']:f"{e['date']} · {e['activity'].title()} · {e['time_period'].title()} · {e['event_id'][:8]}" for e in rows}
            chosen=st.selectbox('Choose an entry to inspect or edit',list(options),format_func=lambda x:options[x])
            selected=next(e for e in events if e['event_id']==chosen)
            with st.expander('Edit selected entry'):
                with st.form(f'edit_event_{chosen}'): 
                    ed=st.date_input('Date',value=date.fromisoformat(selected['date']),key=f'edit_date_{chosen}')
                    ep=st.selectbox('Time of day',PERIODS,index=PERIODS.index(selected['time_period']),format_func=str.title,key=f'edit_period_{chosen}')
                    ea=st.text_input('Activity',value=selected['activity'],max_chars=60,key=f'edit_activity_{chosen}')
                    em=st.number_input('Duration (minutes)',min_value=0,max_value=1440,value=selected['duration_minutes'],key=f'edit_duration_{chosen}')
                    en=st.text_area('Note',value=selected['note'],max_chars=2000,key=f'edit_note_{chosen}')
                    if st.form_submit_button('Save changes',type='primary'):
                        try:
                            updated=make_event(chosen,ed,ep,ea,em,en)
                            st.session_state.events=[updated if e['event_id']==chosen else e for e in events]
                            st.session_state.chat_history=[]
                            st.rerun()
                        except ValueError as exc: st.error(str(exc))
            if selected['note']: st.caption('Note: '+selected['note'])
            if st.button('Delete selected activity'):
                st.session_state.events=[e for e in events if e['event_id']!=chosen]
                st.session_state.chat_history=[]
                st.rerun()
        else: st.info('Your log is empty. Add an activity to begin.')

with chat:
    st.write('')
    section('A CONVERSATION WITH YOUR DATA','Ask your twin','Ask about your history or find something in your notes.')
    c1,c2=st.columns([1.7,1],gap='large')
    with c2:
        with st.container(border=True):
            st.markdown('**A few things to try**')
            st.markdown('◒ &nbsp; What do I usually do on Saturday mornings?  \n◒ &nbsp; Give me an activity summary.  \n◒ &nbsp; What notes mention running outdoors?')
            st.divider()
            st.caption('Local mode uses course-inspired tools and retrieval. It does not call an AI service.')
        with st.expander('Optional: Groq language model'):
            use_groq=st.checkbox('Enable Groq for this session',value=False,key='groq_enabled')
            key=st.text_input('Groq API key',type='password',key='groq_key',help='Used only for your requests. Never commit it to source code.') if use_groq else ''
            consent=st.checkbox('I agree to send my question and selected evidence to Groq.',key='groq_consent') if use_groq else False
            if use_groq: st.caption('Generated text can be wrong. Check the local evidence shown with every answer.')
    with c1:
        if not st.session_state.chat_history:
            st.markdown('<div class="banner"><div class="small">✳ &nbsp; READY WHEN YOU ARE</div><div class="title">Hello, I’m your routine twin.</div><div class="sub">I can help you explore what you’ve shared. Ask me a question to get started.</div></div>',unsafe_allow_html=True)
        for m in st.session_state.chat_history:
            with st.chat_message(m['role']):
                st.write(m['content'])
                if m.get('tool'): st.caption('Tool: '+m['tool'])
                if m.get('local_evidence'):
                    with st.expander('View original local evidence'): st.write(m['local_evidence'])
                if m.get('sources'):
                    with st.expander('View supporting records'):
                        for s in m['sources']:
                            st.write(f"{s.get('date','')} · {s.get('activity','')} · {s.get('event_id','')}")
                            if s.get('note') or s.get('text'): st.caption(s.get('note') or s.get('text'))
        with st.form('ask_form',clear_on_submit=True):
            question=st.text_input('Your question',placeholder='What do I usually do on Saturday mornings?',max_chars=1000,label_visibility='collapsed')
            ask=st.form_submit_button('Ask your twin  ↗',type='primary')
        if ask and question.strip():
            result=answer_question(question,events, {'goal': st.session_state.profile_goal})
            final=result['answer']; local_evidence=None
            # No external call if injection detected or no actual supporting records.
            if use_groq and consent and key and result['sources'] and not looks_like_injection(question):
                if has_pii(question) or has_pii(final) or looks_like_injection(final):
                    final += '\n\nGroq was not called because a possible sensitive detail or instruction was detected. Checks are not comprehensive.'
                else:
                    try:
                        local_evidence=final
                        final=enhance_answer(key, question, local_evidence)
                        if looks_like_injection(final) or has_pii(final):
                            final=local_evidence+'\n\nThe generated response was withheld by a basic safety check.'
                    except Exception:
                        final += '\n\nGroq was unavailable; showing the local answer instead.'
            elif use_groq and (not key or not consent):
                final += '\n\nGroq is off until you provide a key and consent; showing the local answer.'
            st.session_state.chat_history.append({'role':'user','content':question})
            st.session_state.chat_history.append({'role':'assistant','content':final,'tool':result['tool'],'sources':result['sources'],'local_evidence':local_evidence})
            st.rerun()
        if st.session_state.chat_history and st.button('Clear conversation'):
            st.session_state.chat_history=[]; st.rerun()

with scenario:
    st.write('')
    section('EXPLORE THE POSSIBILITIES','What-if studio','Choose a context to see what your past reports suggest.')
    a,b=st.columns([1,1.4],gap='large')
    with a:
        with st.container(border=True):
            st.markdown('**Set your scenario**')
            day=st.selectbox('Day of the week',DAYS,index=5)
            p=st.selectbox('Time of day',PERIODS,format_func=str.title,key='scenario_period')
            st.markdown('<div class="note-card">This compares past reports for your selected context. It does not change your history or control future behavior.</div>',unsafe_allow_html=True)
    with b:
        result=predict_activity(events,day,p)
        with st.container(border=True):
            st.markdown(f'**Your {day.lower()} {p} pattern**')
            st.caption(f"Based on {result['sample_size']} matching reported {'activity' if result['sample_size']==1 else 'activities'}.")
            if result['distribution']:
                for item in result['distribution']:
                    st.markdown(f"**{item['activity'].title()}** &nbsp; · &nbsp; {item['count']}/{result['sample_size']} reports &nbsp; · &nbsp; {item['proportion']:.0%}")
                    st.progress(item['proportion'])
                if result['sufficient']:
                    best=result['distribution'][0]['count']
                    winners=[x['activity'].title() for x in result['distribution'] if x['count']==best]
                    st.success(('Most common: ' if len(winners)==1 else 'Tied for most common: ')+', '.join(winners)+'. This is a historical distribution, not a guarantee.')
                else: st.warning('Insufficient history for a prediction: the prototype requires at least five matching reports. Counts are still shown above.')
            else: st.info('No matching reports yet. Add activities to explore this context.')
            with st.expander('How is this calculated?'):
                st.write('For each activity: matching reports of that activity ÷ all reports for this day and time period. The five-report threshold is a design choice, not proof of statistical reliability.')
                st.write('Matching record IDs:', ', '.join(result['event_ids']) or 'None')

with mobile:
    st.write('')
    section('WEEK 4.4 · MOBILE REALITY','Your twin on WhatsApp','Try the real bot logic here before connecting the Twilio sandbox.')
    mobile_left,mobile_right=st.columns([1.3,1],gap='large')
    with mobile_left:
        st.info('This is a local simulator, not a live WhatsApp connection. Its demo data is separate from your web activity log.',icon='📱')
        if 'wa_demo' not in st.session_state:
            st.session_state.wa_demo=fresh()
            st.session_state.wa_demo_chat=[{'role':'assistant','content':'Welcome! Type a message to start, or choose LANGUAGE SW for Kiswahili.'}]
        with st.container(border=True):
            for msg in st.session_state.wa_demo_chat:
                with st.chat_message(msg['role']): st.write(msg['content'])
            with st.form('wa_demo_form',clear_on_submit=True):
                phone_text=st.text_input('WhatsApp message',placeholder='Try: AGREE',max_chars=2000,label_visibility='collapsed')
                send=st.form_submit_button('Send message  ↗',type='primary')
            if send and phone_text.strip():
                result=process_once(st.session_state.wa_demo,phone_text,'SM'+uuid.uuid4().hex)
                st.session_state.wa_demo_chat.append({'role':'user','content':phone_text})
                st.session_state.wa_demo_chat.append({'role':'assistant','content':result})
                st.rerun()
        if st.button('Reset phone preview'):
            st.session_state.wa_demo=fresh()
            st.session_state.wa_demo_chat=[{'role':'assistant','content':'Welcome! Type a message to start, or choose LANGUAGE SW for Kiswahili.'}]
            st.rerun()
    with mobile_right:
        with st.container(border=True):
            st.markdown('**Try these messages**')
            st.code('AGREE\nHELP\nLOG 2026-10-03 | morning | running | 45 | Felt good\nSTATUS\nPREDICT Saturday | morning',language=None)
            st.caption('Use LANGUAGE SW, KUBALI and HELP to try the Kiswahili command menu.')
            st.divider()
            st.markdown('**Connect a real phone**')
            st.write('Connect directly to Meta’s WhatsApp Cloud API test setup, or use Twilio if available. Both Flask webhook options and setup guides are in the project download.')
            st.caption('Messages here never go to WhatsApp. The Meta integration currently supports text only.')

st.markdown('<div style="border-top:1px solid #e1e9de;margin-top:55px;padding-top:17px;color:#98a89a;font-size:11px;display:flex;justify-content:space-between"><span>MIRROR &nbsp; / &nbsp; YOUR PERSONAL DIGITAL TWIN</span><span>Built for reflection, not prediction certainty.</span></div>',unsafe_allow_html=True)
