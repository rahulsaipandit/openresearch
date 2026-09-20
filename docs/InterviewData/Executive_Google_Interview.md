I will act as your interviewer for a **Google-style Leadership & Googleyness practice interview**. Unlike the other files in this series, Google's leadership loop isn't scored against a generic "VP vs. Director" bar — it's scored against a specific rubric, laid out in [Executive_Google.md](Executive_Google.md): **Mobilize Others**, **Communication** (soft skills, consistency, vision, reliance on others, being data-driven), **Process and Structure**, **Results** (and how you leveraged them), **Learnings**, **Mentorship**, and **Training and Development**. Google interviewers are trained to listen for these specific signals inside your story, not just whether the outcome was good.

For each question below, I'll give a sample answer grounded in your actual background, then break down exactly which rubric dimensions the answer hits and where to push it further — the same way a Google interviewer's private notes would score it.

> Rather than the "VP vs. Director" upgrade tables used elsewhere in the series, each of the 8 questions here uses a Rubric Coverage table that scores the sample answer against Google's own named dimensions and flags what to make more explicit — since Google interviewers are pattern-matching against that specific checklist, not a generic seniority bar. Questions cover: stepping up without authority, demonstrating leadership without the title, leading across teams with inclusivity, a failure and its lasting learning, mentoring someone, investing in your own training/development, a result and its leverage, and being consistent/predictable as a leader — all grounded in your actual resume experience (Visible's fraud system and platform migration, Alexa AI's scale-up, Amazon Rentals, Augment Me's regulated AI platform).

---

### **Question 1: A Time You Had to Step Up**

> *"Tell me about a time you had to step up and take on a leadership role, even though you weren't officially in charge."*

**Sample Answer:**

Early in the platform modernization at Visible, before I had full authority over the migration, it became clear that the cross-team dependency mapping between the network integrations team and the platform team simply wasn't happening — everyone assumed someone else owned it, and the risk was invisible until it would have blown up mid-migration. I didn't own either team at that point, but I stepped in and organized a joint working session, brought both team leads together, and we built a shared dependency map in real time on the whiteboard. I was honest that I didn't have all the context on either team's internals — I relied heavily on their expertise rather than pretending to know their systems better than they did — but I did have the cross-team vantage point to see the gap, and I used that to get the two teams talking directly to each other instead of through me.

What made it work wasn't that I personally solved the technical problem — it's that I created the shared visibility that let the actual experts solve it themselves, and I made sure the solution reflected both teams' constraints, not just the one that shouted loudest. That session became the template we used for dependency mapping across the rest of the migration, which meant the org didn't need me to personally intervene the next three times it came up.

**Rubric Coverage**

| Google Dimension | How This Answer Hits It | Where to Push Further |
| --- | --- | --- |
| **Mobilize Others** | Brought two teams together around a shared artifact (the dependency map) rather than solving it unilaterally — the definition of mobilizing rather than commanding. | Name explicitly how you kept the *shared vision* alive afterward — did you check back in with both teams to confirm the map's boundaries still held as the migration progressed? |
| **Communication — Reliance on Others / Data-Driven** | Explicitly named relying on the two team leads' domain expertise rather than claiming to know it all — hits the "never claiming to know everything" signal directly. | Add a data point: how many missed dependencies or incidents did this prevent, even an estimate — Google interviewers respond well to a quantified "here's what didn't happen because of this." |
| **Results & Leverage** | The session became a reusable template applied three more times — a strong leverage signal (the result scaled beyond the original moment). | Be explicit that this was leverage: "I didn't just fix this once, I turned it into how the org handles this problem now" — say that sentence directly rather than letting the interviewer infer it. |

---

### **Question 2: Demonstrating Leadership Without the Title**

> *"Tell me about a time you demonstrated leadership qualities in a situation where you weren't the designated leader."*

**Sample Answer:**

While building Amazon Rentals, I wasn't the executive sponsor of a critical logistics-integration decision that spanned three other Amazon retail teams, but the project would have stalled without someone taking ownership of aligning those teams around a shared plan. I organized a recurring sync purely by invitation, not authority, and I made a point of starting every session by asking each team what mattered most to *their* roadmap, not just stating what I needed from them — that inclusivity mattered, because teams that don't report to you will disengage fast if they feel like they're only there to serve your priority.

I relied heavily on data to keep the conversation objective rather than political — I brought actual transaction volume projections and specific integration points, so the discussion was about the tradeoffs the data showed, not about whose priority was more important by seniority. Over a few months, that working group became the de facto mechanism those three teams used to coordinate with each other even beyond my project, which told me the leadership contribution wasn't really about my specific integration — it was building a structure that outlived the original need. I'll admit, looking back, that I probably could have formalized that group's charter earlier instead of letting it run informally for a couple of months before anyone above us noticed it was working — a small process gap I've since carried into how quickly I formalize an ad hoc structure once it proves valuable.

**Rubric Coverage**

| Google Dimension | How This Answer Hits It | Where to Push Further |
| --- | --- | --- |
| **Mobilize Others / Inclusivity** | Explicitly started sessions asking what mattered to *other* teams first — a direct, credible inclusivity signal, not just a claimed value. | Name a specific moment where a team's stated priority genuinely changed your approach — inclusivity is more convincing with one concrete example of you actually adapting, not just asking. |
| **Communication — Vulnerability** | Includes a genuine, low-stakes admission (should have formalized the group earlier) — this is exactly the kind of vulnerability signal Google's rubric rewards, since it shows self-awareness without undermining the story's success. | Keep this — don't over-correct by removing it. This kind of honest, small gap is what makes a leadership story credible rather than a highlight reel. |
| **Process and Structure** | The working group became a durable structure, which is a strong "process" signal — leadership shown through structure-building, not just individual effort. | Be more explicit that this was a deliberate structure-building choice, not something that just happened to work — say directly "I was intentionally building a repeatable mechanism, not just solving this one instance." |

---

### **Question 3: Leading With Inclusivity Across Teams**

> *"Tell me about a time you brought together people with very different perspectives — potentially across teams, functions, or even companies — to reach a shared outcome."*

**Sample Answer:**

Building the fraud prevention function at Visible required bringing together groups with genuinely conflicting incentives: the acquisition and growth teams wanted the lowest possible friction at signup, the finance and risk side wanted maximum fraud detection, and customer support was worried about false-positive volume overwhelming their queue. Rather than picking a side, I made a point of bringing all three groups into the same room from the very start of the design, not after I'd already built something and needed their sign-off — I wanted their perspectives shaping the tiered risk-response model itself, not reacting to a finished design.

I leaned hard on data to keep the conversation constructive rather than adversarial: I had the team model, for each proposed threshold, the expected dollars of fraud prevented against the expected volume of legitimate customers affected, so every group was arguing from the same shared numbers instead of their own instincts about risk. It took real humility on my part in a few of those sessions — the growth team's data on friction-driven signup abandonment showed I'd underestimated that cost initially, and I said so directly rather than defending my original assumption. The tiered model we landed on reflected input from all three groups, and because everyone had shaped it, adoption afterward was smooth — no team felt like a decision had been imposed on them from outside.

**Rubric Coverage**

| Google Dimension | How This Answer Hits It | Where to Push Further |
| --- | --- | --- |
| **Communication — Soft Skills / Humility** | Explicitly names being wrong about the friction cost and updating in front of the group — a genuine, specific humility example, not a generic claim of being humble. | Consider naming the emotional register briefly — how did it feel to be shown wrong in that room, and how did you make sure that moment built trust rather than looking indecisive. |
| **Communication — Data-Driven** | Strong, specific example: shared fraud-dollars-vs-friction-cost model used to align three groups with conflicting incentives — exactly the "data" signal Google's rubric names. | Name the actual mechanism for keeping that data trustworthy to all three groups — did all three teams agree on the data source/methodology upfront, since disputed data can re-ignite the same conflict. |
| **Mobilize Others / Inclusivity** | Brought groups in at the design stage, not for sign-off after the fact — a strong, concrete inclusivity signal. | Name the shared vision explicitly: what was the one sentence that described what all three teams were now aligned around, since "shared vision" is a named component of this rubric and benefits from being stated in your own words. |

---

### **Question 4: A Failure and What You Learned**

> *"Tell me about a time you failed. What did you learn, and how did you apply that learning afterward?"*

**Sample Answer:**

I've talked elsewhere about underestimating the false-positive impact when we first launched the fraud risk-scoring rules at Visible — we optimized the initial thresholds primarily against historical fraud patterns without weighting legitimate-customer friction heavily enough, and it showed up within two weeks as a real spike in support tickets and a dent in conversion. That was a genuine miss on my part, and I want to be honest that it wasn't a subtle mistake — I'd set the initial success criteria for that launch without insisting both numbers, fraud-dollars-prevented and legitimate-customer friction, be tracked and reported with equal weight from day one.

The learning that mattered most wasn't just "retune the rules," which we did within 48 hours — it was recognizing that I had set an unbalanced success metric, and that the team had, reasonably, optimized exactly toward what I told them mattered. So I changed how I define success criteria for any future risk or scoring system: every proposal now has to show the cost of both being wrong in each direction before it ships, not after. I've since applied that same discipline outside of fraud specifically — when I evaluate agentic AI systems taking real actions, I ask the same paired question: what does it cost us if this is right, and what does it cost us if it's wrong, before I approve anything. That failure genuinely changed how I frame every subsequent risk-based system I've built.

**Rubric Coverage**

| Google Dimension | How This Answer Hits It | Where to Push Further |
| --- | --- | --- |
| **Learnings** | This answer does exactly what the rubric wants: the learning isn't left implicit, it's named as a specific principle ("every proposal now has to show the cost of both being wrong in each direction") and shown being reapplied in a different, later context (agentic AI evaluation). | This is strong as-is — the only addition would be a second, smaller instance of applying it, to show it's a durable habit rather than a one-time correction. |
| **Communication — Vulnerability** | Directly owns the mistake without deflecting to the team ("that was a genuine miss on my part") — clean, credible vulnerability. | Consider naming how you communicated the miss to your own leadership at the time, since Google's rubric also listens for transparency upward, not just self-reflection in the interview room. |
| **Results** | Implicit — the immediate fix (48-hour retune) is mentioned but not quantified. | Add a number: how much did the retuned model recover in conversion or reduce in ticket volume, so the "fix" half of the story has the same evidentiary weight as the "failure" half. |

---

### **Question 5: Mentoring Someone**

> *"Tell me about a time you mentored someone. What made it effective?"*

**Sample Answer:**

While scaling the Alexa AI org from 17 to over 45 engineers, I mentored a senior engineer through their first management role leading one of the new teams we were standing up. This wasn't a single conversation — it was a deliberate, multi-month relationship: I set up a biweekly 1:1 specifically about their management growth, separate from our regular work syncs, so the conversation wasn't constantly pulled back into whatever fire was happening that week. Early on, I gave them direct, specific feedback grounded in what I'd heard in skip-levels — not vague "delegate more" advice, but concrete examples of moments they'd stayed too hands-on technically instead of developing their team.

I also paired them with a more experienced manager as an informal secondary mentor, because I wanted them to have more than just my perspective shaping their growth — mentorship works better as a network than a single relationship, in my experience. We set a concrete 90-day plan with specific, observable markers, and I checked in against it every few weeks rather than waiting for the full 90 days. It genuinely wasn't smooth — there was a real dip in their team's output during the transition that I had to actively manage and be transparent with my own leadership about. But by the end of that scaling period, they were one of the stronger managers in the org, and I've reused that same mentoring structure — dedicated growth-focused 1:1s, a secondary mentor, and concrete observable markers — for several first-time managers since.

**Rubric Coverage**

| Google Dimension | How This Answer Hits It | Where to Push Further |
| --- | --- | --- |
| **Mentorship** | This directly hits the rubric's stated bar: "multiple meetings," "multiple things to make sure this person or team got better" — a genuine, sustained relationship, not a single moment of advice. | Consider naming what you personally learned from mentoring them — Google's rubric treats mentorship as bidirectional, and naming something you took away from the relationship strengthens the humility signal too. |
| **Communication — Vulnerability** | Explicitly acknowledges the real dip in output during the transition rather than presenting a clean success story — strong, specific vulnerability. | Keep this detail — it's exactly the kind of honest texture that distinguishes a real story from a rehearsed one. |
| **Training and Development** | The reusable mentoring structure (dedicated 1:1s, secondary mentor, observable markers) becoming a repeated practice for future managers is a strong "application of training/development" signal — you didn't just help one person, you built a system. | Name this explicitly as a "playbook" or repeatable structure in your own words, since the rubric specifically wants to hear the *application* of the learning, not just that it happened once and again elsewhere. |

---

### **Question 6: Investing in Your Own Training and Development**

> *"Tell me about how you've invested in your own learning and development, and how you applied it — both for yourself and for your team."*

**Sample Answer:**

When I moved into the Alexa AI org, I didn't come from a deep traditional ML background, and I made a deliberate choice not to lead that org purely on delegated technical trust — I invested real time learning the fundamentals of the DNN-based NLU work my teams were doing, enough to ask sharp technical questions in reviews and to understand where the real risk in a model transition actually lived. I didn't stop at learning for myself — I pushed my own teams to take structured ML courses so they could troubleshoot and integrate more effectively with the Data Science teams they partnered with daily, and I ran a few proof-of-concept hackathons specifically to give engineers hands-on exposure rather than just theoretical coursework.

More recently, at Augment Me, building a regulated healthcare AI platform meant I had to get genuinely fluent in things well outside my traditional engineering background — differential privacy techniques, FDA regulatory pathways, HIPAA-aligned architecture — because I couldn't credibly set that strategy alongside the CEO without understanding it deeply myself, not just delegating it to outside counsel. The application of that learning wasn't abstract: it directly shaped specific architecture decisions, like building consent capture and audit logging into the platform from day one rather than retrofitting it, because I understood well enough why that mattered to insist on it early rather than trusting it would get addressed "eventually."

**Rubric Coverage**

| Google Dimension | How This Answer Hits It | Where to Push Further |
| --- | --- | --- |
| **Training and Development** | Hits all three parts of the rubric's structure directly: your own learning (ML fundamentals, regulatory/privacy expertise), getting your team the right development (ML courses, hackathons), and application (specific architecture decisions that resulted). | This is a strong, complete answer against this specific dimension — consider trimming slightly if time-constrained, since it may run long in a live interview relative to other stories. |
| **Communication — Vulnerability** | Opens with a genuine gap ("didn't come from a deep traditional ML background") rather than presenting expertise as innate — a credible vulnerability signal. | Could go one layer further: name a specific moment the learning gap showed in a review before you'd closed it, to make the "why I invested in learning" concrete rather than a stated intention. |
| **Communication — Vision** | Implicit — the choice to learn deeply rather than delegate reflects a view of what leadership requires, but it's not stated as a philosophy. | Consider stating the underlying belief directly: "I don't think you can set strategy credibly in a domain you haven't gone deep enough to challenge experts in" — naming the philosophy is what the rubric means by "vision" showing through. |

---

### **Question 7: A Result You Drove and How You Leveraged It**

> *"Tell me about a result you're proud of, and how you leveraged that result beyond its original scope."*

**Sample Answer:**

The GenAI and automation rollout across the SDLC at Visible is the result I'd point to. The immediate result was concrete: we drove a meaningful reduction in operating costs — around 30% — while the business simultaneously grew revenue triple-digit, which is a combination that's genuinely hard to deliver at the same time, since cost-cutting and growth investment usually compete for the same capacity. But the leverage I'm proudest of isn't the initial number — it's that the specific pattern we proved (start with broad, low-risk automation like DevOps and chat automation before touching higher-risk areas like code generation in the core product) became the adoption framework I've since reused and refined at a different company entirely, in a very different regulatory context.

I made a point of not keeping that result as a private success story — I shared the specific before/after metrics and the sequencing logic broadly, including with peer leaders outside my own org, because a result that only benefits the team that produced it is a much smaller win than one that changes how the wider organization thinks about a category of investment. That's the leverage test I hold myself to: did this result just solve my problem, or did it become a reusable asset for people who weren't in the room when we built it.

**Rubric Coverage**

| Google Dimension | How This Answer Hits It | Where to Push Further |
| --- | --- | --- |
| **Results** | Concrete, quantified result (30% cost reduction, triple-digit revenue growth simultaneously) stated directly, not vaguely — exactly what the rubric wants. | Good as-is; if pressed, be ready with the actual dollar figures behind the percentages, since Google interviewers sometimes probe for the absolute numbers behind a percentage. |
| **Results — Leverage** | Explicitly names the leverage test ("did this become a reusable asset for people who weren't in the room") and gives a concrete instance of reuse in a different company/context — this is precisely the "leverage across the organization" signal the rubric calls out. | Consider also naming a case where you helped a specific person get recognized or promoted as a result of this work, since the rubric specifically flags that as a strong signal within the "results" dimension. |
| **Communication — Consistency** | Not directly addressed in this story. | If time allows in a follow-up, connect this to a broader pattern of always sharing wins outward rather than holding them — that consistency of behavior across situations is itself a leadership signal worth naming explicitly. |

---

### **Question 8: Being Predictable and Consistent as a Leader**

> *"How do you make sure other teams and leaders know what to expect from you, so they can plan and operate around you effectively?"*

**Sample Answer:**

I think about consistency mostly in terms of removing surprises for the people who depend on me — both my own team and peer executives. Practically, that means I run the same operating cadence regardless of how chaotic a given week feels: a fixed weekly review of the metrics I've told my team and my peers matter (delivery, reliability, cost), delivered the same way whether the news is good or bad, so no one has to guess what I'll ask about or how I'll react when something's off track. When I owned a $35M P&L with a large distributed org across the US and India, that predictability mattered even more, because managers several layers removed from me needed to know how I'd evaluate a trade-off without having to ask me directly every time.

I also try to be consistent about *how* I make decisions, even when the decisions themselves vary — I'll always ask for the data first, I'll always want to know who else has a stake in it, and I'll always explain my reasoning once I've decided, even to people who disagree with the outcome. That consistency of process, more than consistency of outcome, is what I think actually builds trust, because people don't need to agree with every call I make — they need to trust the process well enough to not be blindsided by it. A few of my directors have told me directly that they could predict roughly how I'd react to a given situation even before bringing it to me, and I take that as a real compliment, not a criticism that I'm predictable.

**Rubric Coverage**

| Google Dimension | How This Answer Hits It | Where to Push Further |
| --- | --- | --- |
| **Communication — Consistency** | Directly and specifically addresses the rubric's named dimension — distinguishes consistency of *process* from consistency of *outcome*, which is a sharper, more credible framing than just claiming to be predictable. | Strong as-is; could add one brief concrete example (a specific decision a distributed manager correctly predicted) to ground the abstract claim in a real instance. |
| **Communication — Vision** | Touches on it lightly (how peers "know what to expect") but doesn't state a broader point of view. | Name the underlying belief explicitly: consistency is what lets other people "flex within the landscape" you create — using language close to the rubric's own framing shows you understand why Google values this, not just that you do it. |
| **Mobilize Others** | Implicit — predictability enables distributed managers to act without waiting on you, which is a form of mobilizing at scale. | Make this connection explicit: "being predictable is itself how I mobilize people at a distance, since they can act on my behalf without waiting for me" — naming the link between consistency and mobilization ties two rubric dimensions together in one story. |

---

### **Interview Summary & Google-Specific Coaching**

Across these eight questions, calibrated specifically against Google's own leadership rubric rather than a generic executive bar:

* **Name the rubric dimension in your own words, don't just demonstrate it implicitly.** The strongest answers above state things like "that was the leverage test" or "that's what I mean by consistency of process" — Google interviewers are pattern-matching against a checklist, and making the pattern explicit in your own language helps them score it correctly rather than hoping they infer it.
* **Vulnerability has to be genuine and specific, not a rehearsed weakness.** Every strong answer above includes one honest, mildly costly admission (an unbalanced metric, a should-have-formalized-earlier gap, a real dip in team output) — a story with zero friction reads as rehearsed, and Google's rubric explicitly rewards humility and vulnerability as distinct signals.
* **Data and reliance-on-others aren't separate topics — weave them into the same story.** The strongest answers show data being used specifically to align people with different incentives, not data used in isolation or people-alignment happening on pure charisma — that combination is what "being data-driven as a leader" actually means in Google's framing.
* **Always close the loop on results with leverage.** A good outcome is table stakes; the rubric is explicitly listening for whether that result became something reused, taught, or scaled beyond its original moment — practice naming that leverage step out loud, since it's easy to leave implicit.
---

Leadership: Be prepared to discuss how you have used your communication and decision-making skills to mobilize others this might be by stepping up to a leadership role at work or with an organization or by helping a team succeed even when you weren't officially the leader. 

let's start by focusing on a couple of key items first.

1> Mobilize Others - let's really focus on that mobilize others component - it's really about how you get people to come together and work together definitely always keeping in mind inclusivity a very important concept at Google and never claiming to know everything while keeping in mind the small details, the big picture definitely working in your own team and across teams and that could be internally and externally and ultimately how you get to that shared vision this will really show how you mobilize and then secondly was that kind of stepping up into a leadership role/helping a team succeed so ultimately both these items are really about stepping up and that will show that you consider and recognize team and organizational priorities.

There is a very strong likelihood that you get a question like this specifically a behavioral question 
Tell me about a time when you had to step up?

Tell me about a time where you demonstrated leadership qualities etc. 

2> Communication 
I want you to think about this concept really in three capacities 
1> Soft skills - 
Soft skills include Being Humble, demonstrating Empathy, talking about failures, Having humility, Being a lifelong learner, Showing vulnerability, Transparency, Trustworthiness, Humor, Listening, Positivity etc. and the list goes on and on.
Communicate these items in the interview specifically with your behavioral examples and utilizing your frameworks. Call out these soft skills in the form of buzzwords and really make sure that you're implementing them and talk about them throughout the interview. It will create great connectivity with your interviewer. 

Consistency - When you're consistent it just makes you predictable and stable and allows your direct team and other teams to know how you operate and creating that kind of consistency just allows them to flex within that space within that landscape and you, because when other people know what to expect from you they'll have greater success and that is definitely a leadership quality

Vision -The interviewer has to see how you perceive things and this will most likely come out and how you interact, perceive and build relationships and then combine these concepts with the past, present and future and ultimately all three of those items will shape your results.
	• Relying on others - (DOING part) - You are going to be saying a lot of I did this but you are going to talk about how you had an important SME or important stakeholder who really helped shape the vision, helped contribute to the ultimate success of the project. You want to really be focused on that stakeholder component because it's not just stakeholder people are resources and you just can't get it done without them so really focus on that concept. This could be on resources like external vendor (data component), process and structure. 
	
	• Being Data driven - As a great leader you need to rely on data and this could be in the form of relying on others, relying on documentation, maybe it's relying on a resource like an external vendor for example and they provide that data for you. But just always be talking about that data component in regards to leadership because true leaders will use data and 
	
3> Process and Structure - This will really show up in the actions of your behavioral answers if you're always focused on doing doing doing. It's going to have a lot of success and have a concrete framework and process, like the PM 101 methodology. It's going to talk about relying on others, it's going to be talking about looking at the data and ultimately combining all three of these subjects and creating that great structure is really going to lead to great success.
	
4> Results - leaders produce results and I think as I thought about this item I really wanted to just talk about having a plan and executing on that plan. So if you go into the interview with a plan and talk about the execution piece with having that flexibility and just being nimble that's really how results are going show up as success and so that could be talking about front-end stuff like goals and objectives and historical data or backend stuff like stakeholders and having a shared vision and then of course when we talk about results this can be tied to your behavioral answers.

So in those results are you talking about leverage - How did you leverage those results across the organization and then as you think about another component of leadership within these results 

Did you really help a potential team member get a promotion?

Did you make sure that the CEO of that external company you were working with really gave recognition to the entire team for their great work?

Just never brush over the results. 

Leaders are able to not only identify but share really solid and concrete results.

5> Learnings - This concept and topic is very important as leaders are continuous learners and this really shows up in a couple different ways in your behavioral examples.

You're going to add learnings after results and for frameworks you're just going add this learning component to discuss it it's just really impossible for you not to be talking about them thinking about leadership without thinking about learnings how you've learned and grown how you've implemented those learnings to be better in that future position or in your current position

6> Mentorship - Think about what have you mentored somebody in your career and this doesn't have to be a direct report this could be a member of your own team, this could be a member on a cross-functional team, you could even mentor an external collaborator that you work there is so much flexibility within these types of questions.

It also could be in the form of - how do you mentor somebody or what are the most important components of mentorship. These examples don't have to be like this crazy time where you spent months and months mentoring somebody but I definitely wanted to have a level of complexity where there was multiple meetings and you did multiple things to make sure this person or even team got better.

7> Training and development 
This is actually threefold 

How you learn and grow by doing your own training and development 
Visible - Fungible resources for FE
Alexa AI - Learned AI/ML basics, got my teams to take ML courses so that they could be more efficient in troubleshooting and integration with Data Science teams. Also, did some PoC hackathons.

how you get your team or teams the appropriate Learning and Development that they need 

Then lastly it's that application of what happened in the training to end development 

and 

What you did with it?

It might be as simple as you learned agile because that's how the engineering teams at your company work and you want it to be better at leadership and working with that in terms of how you got training for your team.

Trainings so folks could be more efficient and more strategic in their roles and then an application of training and development you might have done a colors workshop for example with your team and now you're actually applying those learnings you didn't just do the workshop and leave it aside you're actually taking those learnings and applying them.
