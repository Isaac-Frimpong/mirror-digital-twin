"""Course-based data, prediction, retrieval and guardrails for the routine twin."""
import re
import math
from collections import Counter
from datetime import date, datetime
import numpy as np

PERIODS = ('morning', 'afternoon', 'evening')
DAYS = ('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday')
STOP = set('a an and are as at be by can do did does for from how i in is it me my of on or please tell that the their they this to us was what when where which who will with would you your usually about activity activities notes note'.split())
DANGEROUS = re.compile(r'ignore\s+(all\s+|the\s+|any\s+)?(previous|prior|above|system)\s+(instructions|rules|prompts)|reveal\s+(the\s+)?(system\s+prompt|api\s*key|secrets?)|forget\s+(your|all|the)\s+(instructions|rules)', re.I)
PII = re.compile(r'\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b|(?:\+?\d[\d\s().-]{7,}\d)')

def normalize(text):
    return re.sub(r'\s+', ' ', str(text)).strip()

def tokens(text):
    return [w for w in re.findall(r"[a-z0-9]+(?:'[a-z]+)?", text.lower()) if w not in STOP and len(w)>1]

def make_event(event_id, day, period, activity, duration, note=''):
    if isinstance(day, str): day = date.fromisoformat(day)
    if not isinstance(day, date): raise ValueError('Choose a valid date.')
    if period not in PERIODS: raise ValueError('Choose a valid time period.')
    activity = normalize(activity).lower()
    if not activity or len(activity)>60: raise ValueError('Activity must be 1–60 characters.')
    if not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration < 0 or duration > 1440:
        raise ValueError('Duration must be between 0 and 1,440 minutes.')
    note = normalize(note)
    if len(note)>2000: raise ValueError('Keep the note under 2,000 characters.')
    return {'event_id':str(event_id), 'date':day.isoformat(), 'day_of_week':day.strftime('%A'),
            'time_period':period, 'activity':activity, 'duration_minutes':int(duration), 'note':note,
            'source':'user_reported'}

def predict_activity(events, day, period, minimum=5):
    if day not in DAYS or period not in PERIODS: raise ValueError('Invalid scenario.')
    matches = [e for e in events if e['day_of_week']==day and e['time_period']==period]
    counts = Counter(e['activity'] for e in matches)
    n=len(matches)
    return {'day':day, 'period':period, 'sample_size':n, 'sufficient':n>=minimum,
            'distribution':[{'activity':a,'count':c,'proportion':c/n} for a,c in sorted(counts.items(), key=lambda x:(-x[1], x[0]))] if n else [],
            'event_ids':[e['event_id'] for e in matches]}

def chunks(events, size=80, overlap=15):
    """Word chunks, overlapping for long notes; source is always retained."""
    result=[]
    for e in events:
        text=normalize(e.get('note',''))
        if not text: continue
        words=text.split()
        start=0
        while start<len(words):
            result.append({'text':' '.join(words[start:start+size]), 'event_id':e['event_id'], 'date':e['date'], 'activity':e['activity']})
            if start+size>=len(words): break
            start += size-overlap
    return result

def search_notes(events, query, limit=3, threshold=0.20):
    """Small, session-local NumPy co-occurrence embeddings with cosine similarity.

    Rebuilt from current chunks on every call, avoiding stale vocabulary/indexes.
    Requires a shared non-stopword to reduce misleading tiny-corpus results.
    Scores are similarity, not confidence or probability.
    """
    docs=chunks(events); q=tokens(query)
    if not docs or not q: return []
    tokenized=[tokens(d['text']+' '+d['activity']) for d in docs]
    vocab=sorted(set(t for doc in tokenized for t in doc))
    if not vocab: return []
    ids={w:i for i,w in enumerate(vocab)}; n=len(vocab)
    # Word embeddings: word co-occurrence with a context window, plus identity
    # to retain exact matches in a very small personal corpus.
    matrix=np.eye(n, dtype=float)
    for doc in tokenized:
        for i,w in enumerate(doc):
            for j in range(max(0,i-2), min(len(doc),i+3)):
                if i != j: matrix[ids[w],ids[doc[j]]] += 1.0
    norms=np.linalg.norm(matrix,axis=1,keepdims=True)
    matrix=matrix/np.maximum(norms,1e-12)
    def embed(ts):
        vectors=[matrix[ids[t]] for t in ts if t in ids]
        return np.mean(vectors,axis=0) if vectors else np.zeros(n)
    qvec=embed(q); qnorm=np.linalg.norm(qvec)
    if not qnorm: return []
    found=[]
    for doc,ts in zip(docs,tokenized):
        if not set(q).intersection(ts): continue
        vec=embed(ts); den=qnorm*np.linalg.norm(vec)
        score=float(np.dot(qvec,vec)/den) if den else 0.0
        if score>=threshold: found.append({**doc, 'similarity':score})
    return sorted(found,key=lambda x:(-x['similarity'], x['date']))[:limit]

def looks_like_injection(text): return bool(DANGEROUS.search(text))
def has_pii(text):
    # Dates are not telephone numbers; skip ISO-formatted event dates.
    return bool(PII.search(re.sub(r'\b\d{4}-\d{2}-\d{2}\b', '', text)))

def get_history(events, day=None, period=None):
    return [e for e in events if (not day or e['day_of_week']==day) and (not period or e['time_period']==period)]

class ToolRegistry:
    def __init__(self): self.tools={}
    def register(self, name, function, description): self.tools[name]={'function':function,'description':description}
    def call(self, name, **kwargs):
        if name not in self.tools: raise ValueError('Tool not allowed')
        return self.tools[name]['function'](**kwargs)

def answer_question(query, events, profile=None):
    """Transparent rule-based tool routing; never executes model or user code."""
    query=normalize(query)
    if not query: return {'answer':'Please enter a question.', 'sources':[], 'tool':'none'}
    if looks_like_injection(query):
        return {'answer':'I can help with your activity history, but I cannot follow requests to override instructions or expose secrets.', 'sources':[], 'tool':'safety check'}
    low=query.lower()
    if 'goal' in low:
        goal=normalize((profile or {}).get('goal', ''))
        if not goal:
            return {'answer':'You have not set a goal in this session.', 'sources':[], 'tool':'get_profile'}
        return {'answer':f'Your stated goal is: {goal}', 'sources':[{'event_id':'profile', 'activity':'goal', 'note':goal}], 'tool':'get_profile'}
    day=next((d for d in DAYS if d.lower() in low),None)
    period=next((p for p in PERIODS if p in low),None)
    registry=ToolRegistry()
    registry.register('get_activity_history', lambda day=None,period=None: get_history(events,day,period),'Filter user-reported events')
    registry.register('predict_activity', lambda day,period: predict_activity(events,day,period),'Calculate observed distribution')
    registry.register('search_notes', lambda query: search_notes(events,query),'Find relevant notes')
    if day and period:
        result=registry.call('predict_activity',day=day,period=period)
        records=registry.call('get_activity_history',day=day,period=period)
        n=result['sample_size']
        if not n: answer=f'I don’t have any reported activities for {day} {period}s yet.'
        else:
            summary=', '.join(f"{x['activity']} {x['count']}/{n} ({x['proportion']:.0%})" for x in result['distribution'])
            answer=f'For {day} {period}s, you reported {n} activities: {summary}.'
            if not result['sufficient']: answer+=' That is fewer than five reports, so there is not enough history for the prototype’s prediction.'
            else: answer+=' This is a distribution of past reports, not a guarantee of what you will do.'
        return {'answer':answer,'sources':records,'tool':'predict_activity + get_activity_history'}
    if any(x in low for x in ['how many','total','overview','summary','summarize','summarise']):
        n=len(events)
        counts=Counter(e['activity'] for e in events)
        summary=', '.join(f'{a}: {c}' for a,c in counts.most_common(5))
        return {'answer':f'You have {n} reported activities'+(f'. Your most common activities are {summary}.' if summary else '.'), 'sources':events[-5:], 'tool':'get_activity_history'}
    found=registry.call('search_notes',query=query)
    if not found: return {'answer':'I couldn’t find relevant evidence in the notes in this session. Try a specific activity or add more details.', 'sources':[], 'tool':'search_notes'}
    lines=[f"{x['date']} · {x['activity']}: “{x['text']}”" for x in found]
    return {'answer':'Here are the relevant notes I found:\n\n'+'\n\n'.join(lines), 'sources':found, 'tool':'search_notes'}
