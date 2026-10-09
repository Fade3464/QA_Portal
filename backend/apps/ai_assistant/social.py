"""Non-analytical turns: no QA query, invented availability, or context reset.

These deliberately bounded replies answer questions about the ASSISTANT only.
Anything containing a business request is passed to the semantic investigation.
"""
import re


def social_response(text):
    q = re.sub(r'\s+', ' ', text.casefold().strip()).replace('\u2019', "'")
    for bad in ('avaialble', 'availabe', 'avaliable', 'avilable'):
        q = q.replace(bad, 'available')
    q = q.strip(' !?. ,')
    # Do not swallow "Hi, who has pending reports?" or "Are you available to
    # check team performance?". Social is a separate, narrowly-scoped channel.
    business = r'\b(?:reports?|evaluations?|agents?|teams?|leaders?|dialers?|projects?|calls?|backlog|scores?|violations?|reviews?|reviewing|critical|pending|performance|worst|best)\b'
    if re.search(business, q) and not re.fullmatch(r'(?:what can you do|what do you do|can you help with qa)', q):
        return None
    if q not in {'hi there', 'hello there'}:
        q = re.sub(r'^(?:hi there|hello there|hi|hello|hey)[, !.]+', '', q).strip(' !?.,')
    if re.fullmatch(r"(?:hi|hello|hey|hi there|hello there|good (?:morning|afternoon|evening)|howdy|greetings)", q):
        return 'Hello! What would you like to check in CallLens?'
    if re.fullmatch(r"(?:are you|r u|you)(?: still)? (?:there|here|available|online|working|ready|awake)(?: now| today| to help(?: me)?)?|can you (?:hear|help) me|hello anyone there", q):
        return "Yes, I'm here and ready to help. What would you like to check?"
    if re.fullmatch(r"how (?:are you|r u|is it going|are things)(?: doing| feeling)?(?: today)?|how(?:'s| is) (?:your day|it)(?: going)?|you (?:ok|okay)|what(?:'s| is) up", q):
        return "I'm here and ready to help. How can I help you today?"
    if re.fullmatch(r"(?:thank you|thanks|thank you very much|thanks a lot|cheers|great|awesome|ok|okay|got it)(?: so much| for your help)?", q):
        return "You're welcome. We can continue with your previous analysis or start a new question."
    if re.fullmatch(r"(?:bye|goodbye|see you|see you later|good night)", q):
        return 'Goodbye! Your saved conversation will be here when you return.'
    if re.fullmatch(r"who are you|what(?:'s| is) your name|what are you|are you (?:human|a person|a bot|real)|who (?:made|created|built) you", q):
        return "I'm CallLens's AI assistant, not a person. I help investigate the QA information your account is permitted to access. I'm a prototype, so verify important conclusions against the reports."
    if re.fullmatch(r"(?:do you have (?:feelings|emotions)|are you (?:happy|sad|tired)|how old are you|what is your age|where do you live|where are you from)", q):
        return "I don't have a personal life or human feelings. I'm software here to help you with CallLens."
    if re.fullmatch(r"(?:what can you do|what do you do|can you help(?: me)?|help|can you help with qa)", q):
        return 'I can help investigate authorized QA scores, recurring mistakes, team performance, review backlogs, and Call Library counts. I cannot send emails or change reports. Important findings still need independent verification.'
    return None


SOCIAL_TOPICS = {'greeting', 'availability', 'wellbeing', 'identity', 'personal', 'capabilities', 'thanks', 'goodbye'}

def classified_social_reply(topic):
    """LLM can classify unfamiliar personal wording, never supply business facts.

    This port has no database, QA history or runtime/model-health claim. It
    complements fast local recognition without a list of every possible phrase.
    """
    examples = {'greeting':'hello', 'availability':'are you available',
                'wellbeing':'how are you', 'identity':'who are you',
                'personal':'do you have feelings', 'capabilities':'what can you do',
                'thanks':'thank you', 'goodbye':'goodbye'}
    return social_response(examples[topic]) if topic in examples else None

def permits_social_classification(text):
    """Mixed business requests still require analytics, not a conversational escape."""
    return not re.search(r'\b(?:reports?|evaluations?|agents?|teams?|leaders?|dialers?|projects?|calls?|backlog|scores?|violations?|reviews?|reviewing|critical|pending|performance|worst|best)\b', text, re.I)
