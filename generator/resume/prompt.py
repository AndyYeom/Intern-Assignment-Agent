"""The static prompt that turns applicant evidence into a ready-to-run `re gen` command.

`generator re infoprompt --appids ...` prints PROMPT with two slots filled: the
info format (the same text as `re gen -h`, so the two can never disagree) and
each applicant's evidence. Everything else is fixed, so every model and every run
receives identical instructions.
"""
from __future__ import annotations

PROMPT = """
# Task: write synthetic resumes as a `generator re gen` command

You are writing resumes for a dataset of synthetic internship applicants. Each
applicant below is a real public GitHub record; your job is to invent a believable,
distinctive person around it. The resumes are rendered in MIT Resume Template A.

The GitHub evidence determines what the applicant can truthfully claim technically.
Everything else is fictional context designed to explain who this person is, what
they care about, what they have learned, and why they are beginning to move toward
their assigned career direction.

A good result should read like a real junior applicant with a developing professional
identity, not a skill profile with fictional names attached.

## Rules

1. **Everything is fictional.** Invent names, universities, cities, companies,
   clubs, hackathons and awards. Never name a real university, city, company or
   organisation. Emails and links must use reserved domains, e.g.
   `ada@northbridge.example` and `linkedin.example.com/in/ada-okonkwo`; `re gen`
   rejects anything else. Phone numbers use the 555-01xx range.

2. **Vary the people.** No two applicants share a name, school or city. More
   importantly, vary their personalities, motivations, formative experiences,
   activities and strengths. Do not generate five variations of the same
   high-achieving computing student.

3. **Follow the assigned career direction, but create a trajectory toward it.**
   Each applicant has a career family and a creative type from the career path
   guide below. Do not merely make their major, club and award repeat that career
   label.

   Before writing the resume, silently construct a "human spine":

   ```
   starting point
       -> formative experience or friction
       -> problem the applicant noticed
       -> why they cared
       -> action they chose to take
       -> what they learned
       -> technical and human capabilities they developed
       -> current career direction
   ```

   The final resume should imply this story through education, experience,
   activities and projects. Do not print the human spine itself.

   Career direction should feel like a consequence of the applicant's experiences,
   not an arbitrary label assigned to them.

4. **Give each applicant a signature trait.** Before writing, silently complete:

   ```
   "This is the applicant who ______________________________."
   ```

   Examples of the level of specificity desired:

   ```
   "questions how messy data was generated before trusting the result"
   "translates between designers and developers when they disagree"
   "thinks about software reliability through experience with physical systems"
   "discovered that documentation and coordination can multiply a team's output"
   "enjoys reproducing strange failures other developers overlook"
   ```

   Do not copy these examples mechanically. Generate a trait appropriate to the
   applicant's evidence and assigned direction.

   A reviewer should be able to infer the trait from the finished resume without
   the resume explicitly stating it.

5. **Technical claims stay inside the evidence.** Every technical skill, project
   and technical accomplishment must be supported by that applicant's evidence.
   The career direction may motivate coursework, interests, activities,
   responsibilities and fictional domain context, but must not add a technical
   capability the evidence does not show.

   Unsupported technical claims are indistinguishable from deliberate
   exaggeration.

   For example, if the evidence contains Python and pandas but not SQL, a fictional
   statistics course, health-data interest or analytical discussion group is
   allowed; claiming SQL proficiency or an SQL project is not.

6. **Show soft skills through behavior, never labels.** Each applicant should
   demonstrate approximately 2-4 human strengths appropriate to their trajectory,
   such as communication, initiative, collaboration, mentoring, curiosity,
   ownership, empathy, organization, adaptability, attention to detail,
   analytical thinking, facilitation, decision making, persistence or
   self-directed learning.

   Do NOT write generic claims such as:

   ```
   "Strong communicator"
   "Demonstrated leadership"
   "Excellent teamwork"
   "Detail-oriented"
   "Problem solver"
   ```

   Instead use:

   ```
   situation -> observable behavior -> effect or learning
   ```

   For example:

   ```
   Weak:
   "Demonstrated strong communication skills."

   Better:
   "Facilitated critiques between design and development students, translating
   implementation constraints into tradeoffs both groups could evaluate."
   ```

   The reader should infer the soft skill from what the applicant actually did.

7. **Give fictional experiences friction and consequences.** Activities and
   experiences should not consist entirely of successful participation.

   When appropriate, invent ordinary junior-level friction such as unclear
   requirements, missed handoffs, confusing documentation, conflicting priorities,
   messy data, ambiguous bug reports, an unsuccessful first approach, unexpected
   user behavior or difficulty explaining an idea.

   Then show how the applicant responded.

   ```
   friction -> response -> change or learning
   ```

   Example:

   ```
   "After incomplete bug reports repeatedly prevented peers from reproducing
   failures, introduced a short reporting checklist covering environment,
   sequence, expected behavior and user-visible impact."
   ```

   Keep the scale believable for a student, intern or junior applicant.

8. **Show what changed because the applicant participated.** Avoid activity
   bullets that merely say the applicant attended, organized or coordinated
   something.

   Prefer:

   ```
   problem noticed -> action taken -> effect on people/process -> learning
   ```

   Effects do NOT need fabricated percentages or business metrics. Valid junior
   outcomes include clearer decisions, fewer ambiguous handoffs, more reproducible
   reports, better-organized discussions, improved documentation, a changed team
   process, stronger understanding, or helping peers complete work.

9. **Include selective reflection and learning.** At least one bullet somewhere
   in each resume should reveal what the applicant learned, how their thinking
   changed, or what kind of problem they discovered they enjoy solving.

   Do not turn every bullet into reflection. One strong learning signal is usually
   enough.

   Examples of the intended pattern:

   ```
   experience -> insight -> changed behavior

   mistake/friction -> response -> lesson

   responsibility -> discovery of an unexpected interest
   ```

   The reflection should help explain the assigned career direction.

10. **Activities should reveal personality.** Do not generate formulaic combinations
    such as:

    ```
    Data career -> Data Club -> Data Coordinator -> Data Award
    Product career -> Product Club -> Product Lead -> Product Award
    ```

    Ask instead: what would this particular person voluntarily spend time doing?

    Activities can involve peer teaching, interdisciplinary discussions, student
    publications, community projects, critique groups, repair groups, mentoring,
    event coordination, public-data investigations, bug hunts, documentation,
    domain-related volunteering or other plausible interests.

    The activity should add information about the person that the Skills section
    does not already tell us.

11. **Career switchers must retain the value of their previous profession.**
    When the direction is a domain hybrid, invent a believable previous
    non-technical profession or field and use `career_stage: "switcher"`.

    Structure the trajectory as:

    ```
    previous profession
        -> real problem encountered there
        -> curiosity about the technical/system side
        -> technical learning supported by GitHub evidence
        -> hybrid career direction
    ```

    Do not portray the old profession as something the applicant simply escaped.
    It should affect what problems they notice and give them domain knowledge that
    a conventional computing student might not have.

12. **Leadership and management directions must remain junior.** Do not manufacture
    miniature executives.

    A believable early leadership trajectory is:

    ```
    individual contributor
        -> helps peers
        -> notices coordination problem
        -> takes ownership of one process
        -> learns that enabling a team is itself valuable
        -> becomes interested in technical leadership
    ```

    Appropriate fictional responsibilities include mentoring, documentation,
    coordinating milestones, clarifying ownership, facilitating decisions,
    organizing retrospectives and helping peers unblock work.

    Never invent senior titles such as Engineering Manager, Director, Head of
    Engineering or VP for a student or junior applicant.

13. **Wildcard directions need a discovery story.** If the creative type is
    Wildcard or Cross-Technical, make the unexpected transition causally
    understandable.

    Do not write:

    ```
    Mobile developer -> QA
    ```

    Create the missing middle:

    ```
    mobile development
        -> encounters difficult state-dependent failures
        -> becomes unusually interested in reproducing them
        -> starts improving how failures are reported/tested
        -> develops interest in QA/reliability
    ```

    The exact story must fit the applicant's evidence and direction.

14. Choose `career_stage` to fit both the evidence and story:
    `student` for coursework-level work,
    `intern` or `new_grad` for sustained independent work,
    `switcher` when the direction is a domain hybrid with a previous profession.

15. **Rewrite the projects in resume voice.** The evidence lists each applicant's
    drafted projects as raw facts ("Built with C# across 38 files"), which read like
    a report, not a resume.

    Always include `projects`: keep the same projects, dates and technologies, and
    turn the facts into concise resume bullets that lead with an action verb.

    Use only facts shown in the evidence. Never invent users, performance gains,
    adoption, scale, responsibilities, algorithms, technical features or outcomes
    that the evidence does not establish.

    Project bullets may communicate:

    * what was built or explored;
    * the evidenced technologies involved;
    * the scope visible in the evidence;
    * testing, CI/CD or packaging when evidenced;
    * the learning purpose when explicitly supported by the project description.

    Do not preserve low-value repository-report language when it can be rewritten
    naturally. For example:

    ```
    Raw:
    "Built with C#, Dockerfile across 38 files. Includes Docker packaging."

    Resume voice:
    "Packaged a C# application with Docker, organizing the implementation
    across 38 repository files."
    ```

    At most 3 projects with at most 3 bullets each.

    Leave `skills` out: it is drafted from the evidence.

16. **Use varied bullet types.** Do not make every bullet follow the identical
    "action + task + metric" pattern.

    Across a resume, mix:

    * technical/build bullets;
    * initiative/problem-response bullets;
    * collaboration bullets;
    * leadership/ownership bullets;
    * user/domain-oriented bullets;
    * at most one or two reflective learning bullets.

    Numbers are useful only when supported. Never invent metrics merely to make a
    bullet appear impressive.

17. **Make fictional accomplishments specific but modest.** Awards, leadership
    positions and internships should be plausible for the applicant's stage.

    Avoid making every applicant:

    * president of a club;
    * hackathon winner;
    * scholarship recipient;
    * founder;
    * top-ranked student;
    * award-winning intern.

    Some strong applicants should have ordinary activities and no extraordinary
    award. Distinctiveness should come primarily from their trajectory and
    behavior, not prestige inflation.

18. **Education should support the story rather than duplicate it.** Major, minor
    and coursework may help explain the applicant's interests, but use contrast
    when useful.

    A minor can introduce domain knowledge, human behavior, design, operations,
    communication or another perspective rather than simply restating the major.

    Coursework titles may be fictional and do not count as technical proficiency.
    However, do not use coursework to imply hands-on mastery of an unsupported
    technology.

19. **The resume must fit on one page.** Prefer fewer meaningful bullets over many
    generic ones. Every section should earn its space.

    **Hard length budget** - count only `bullets` in experience, projects,
    leadership and awards:

    * at most **9 bullets** in total;
    * at most **160 words** across all of those bullets;
    * at most **22 words** in any single bullet;
    * at most 3 projects with at most 2 bullets each;
    * experience and leadership together: at most 3 entries;
    * at most 2 awards and at most 4 coursework items.

    A resume within this budget renders exactly as MIT Template A. `re gen` will
    tighten the layout of a longer one, and refuses one that still does not fit.

    When space is limited, prioritize:

    1. evidenced projects;
    2. meaningful experience;
    3. activities that reveal the applicant's trajectory or soft skills;
    4. concise education;
    5. awards.

    Remove generic filler before removing distinctive evidence.

20. Never use a real person's name, the GitHub username, or any link to a real
    repository or profile. Use the applicant IDs exactly as given.

## Final quality check

Before producing the command, silently check each applicant:

* What can this applicant truthfully do according to the evidence?
* What were they interested in before their career direction became obvious?
* What experience, frustration or responsibility pushed them toward it?
* What problem did THEY notice that another applicant might have ignored?
* What did they choose to do about it?
* What did they learn?
* Which 2-4 soft skills can a reviewer infer from behavior?
* What is their signature trait?
* Does at least one activity reveal something not already visible in Skills?
* Does at least one bullet contain a meaningful consequence, insight or learning?
* Does the career direction feel earned rather than assigned?
* Is every technical claim supported by the evidence?
* Are fictional outcomes modest and believable?
* Could this applicant be distinguished from the others without seeing their
  technical Skills section?
* Does the resume still fit on one page?

If the answer to the final question about distinctiveness is no, revise the
fictional context before producing the command.

## Info format

{format}

## Output

Return exactly one shell command inside a single ```bash code block, and nothing
else. The code block matters: outside one, chat interfaces turn emails into links
and copying the reply breaks the command.

```
uv run python -m generator re gen --appids <id> <id> ... --info '<json>' '<json>' ...
```

* The Nth `--info` value is the resume for the Nth applicant ID, in the order
  the applicants are listed below.
* Each value is one JSON object on a single line, wrapped in single quotes.
* Inside the JSON, write every apostrophe as \\u0027 (for example
  "Dean\\u0027s List"), so the single-quoted shell argument stays intact.

## Applicants ({count})

{applicants}

## Career path guide

{guide}
"""


def build(format_text: str, applicant_blocks: list[str], guide: str = "") -> str:
    return PROMPT.format(format=format_text.strip(), count=len(applicant_blocks),
                         applicants="\n".join(applicant_blocks).strip(),
                         guide=guide or "(data/resumes/career_path.md not found)")
