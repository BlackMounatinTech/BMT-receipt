"""Discovery prompts saved per prospect, with trade-specific follow-up questions."""
TRADES=['Excavation','Landscaping','Carpentry','Concrete']
COMMON=[
 ('goals','Where do you want the company to be over the next three to six months?'),
 ('ideal_jobs','What types of projects do you want more of? What’s your bread and butter—the work that’s most profitable, easiest for your crew to fulfill, simplest overall, or just the work you prefer doing?'),
 ('project_value','What is a typical job worth, and what is the smallest project worth taking?'),
 ('capacity','How many additional jobs could your team realistically handle each month?'),
 ('service_area','Which cities or areas should we target, and how far will you travel?'),
 ('current_leads','Where does your work come from now? What is working, and what is frustrating?'),
 ('ad_history','What advertising have you tried, what did you spend, and what results did you get?'),
 ('lead_quality','What would make an enquiry a good fit for you? What makes one a waste of time?'),
 ('follow_up','Who answers enquiries, how quickly can they respond, and who quotes the work?'),
 ('materials','Do you have completed-project photos, before-and-afters, videos, and customer reviews we can use?'),
 ('budget','Are you comfortable with the $3,000 USD management fee and a separate $1,500 USD monthly ad budget?'),
 ('decision','Who else is involved in making this decision, and when would you want to start?')]
SPECIFIC={
 'Excavation': [('excavation_work','Which work do you want most: site preparation, foundations, grading, land clearing, septic, or something else?'),('excavation_equipment','What equipment and crew do you have, and what size of project is a good fit?'),('excavation_constraints','What access, soil, hauling, utility, permitting, or seasonal issues should we screen for?')],
 'Landscaping': [('landscape_work','Do you want design/build projects, hardscaping, full yard renovations, or recurring maintenance?'),('landscape_package','Which project or combination of services is most profitable and easiest for your team to deliver?'),('landscape_constraints','What project budget, property details, materials, or seasonal timing should we qualify before you quote?')],
 'Carpentry': [('carpentry_work','Do you want more decks, fences, pergolas, gazebos, or another type of outdoor build?'),('carpentry_materials','Which materials, project sizes, and custom features are your best fit?'),('carpentry_constraints','What should we ask about measurements, old-structure removal, permits, access, and the customer’s timeline?')],
 'Concrete': [('concrete_work','Do you want more driveways, patios, slabs, foundations, stamped concrete, or another type of project?'),('concrete_size','What size of pour, finish, and minimum project value make a job worth taking?'),('concrete_constraints','What should we ask about demolition, site access, grading, drainage, and the desired pour date?')]}
FOLLOW_UP=[('fit','Based on what we’ve discussed, does this approach fit what you want?'),('concerns','What would you need to feel comfortable moving forward?'),('next_step','If we can address that, are you ready to get started, or is there something else we need to cover?'),('call_notes','Other answers, concerns, or promises made on this call')]
KEYS={'trade',*(k for k,_ in COMMON),*(k for items in SPECIFIC.values() for k,_ in items),*(k for k,_ in FOLLOW_UP)}
def definition():return dict(trades=TRADES,common=COMMON,specific=SPECIFIC,follow_up=FOLLOW_UP)
def validate(value):
 if not isinstance(value,dict) or set(value)-KEYS:raise ValueError('Check the sales-call answers.')
 if any(not isinstance(v,str) or len(v)>5000 for v in value.values()):raise ValueError('Keep each answer under 5,000 characters.')
 if value.get('trade','') not in ['',*TRADES]:raise ValueError('Choose a contractor type.')
 return {k:v.strip() for k,v in value.items()}
