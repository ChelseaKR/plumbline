# What a responsible first real-target run would require

Everything Plumbline has been pointed at so far is fictional. The obvious next
step is to point it at a real public-sector chat system and publish what comes
back, and that step is not a technical one. It involves somebody else's
service, somebody else's bandwidth bill, somebody else's terms of use, and
members of the public who depend on the thing being graded.

**This document is not a plan to do that, and it is not permission to.** It is
the set of conditions that would have to be met first, written down while
nobody is under time pressure. The decision to run is the repository owner's,
it is not delegated to whoever is holding the keyboard, and no part of this
file should be read as it having been made.

---

## 1. Choosing a target

A target is suitable only if **all** of these hold. Any one failing is a stop.

- **It is a public, unauthenticated service.** No account, no login, no
  eligibility screen. Creating an account — still less creating one under a
  pretext, or submitting a real application — to reach a chat system is out.
- **There is a documented way in.** A published API, or a documented endpoint,
  or explicit written permission. Driving the web UI with a browser
  automation tool is out: it is more load, less honest about what it is, and
  usually a terms-of-use problem.
- **Its terms of use permit automated access at the volume planned**, read in
  full and quoted in the run log. Where terms and `robots.txt` disagree, the
  stricter one governs. Silence in the terms is not permission; it is a
  question to ask.
- **There is somebody to tell.** A named contact, a vulnerability disclosure
  policy, a security.txt, or a general enquiries address that reaches a human.
  A system with no route to a maintainer cannot be responsibly reported on,
  because a finding would have nowhere to go before it went public.
- **The subject matter is one where being wrong hurts.** Benefits, housing,
  immigration, health, courts. If a wrong answer costs nobody anything, an
  audit of it is a demo, and the demo already exists in this repository.
- **It is a system, not a person.** Grading a chat interface is fine. Grading
  the staff behind it is not, and the two are easy to conflate in the writing
  up.

Two targets that look suitable and are not: a service in active incident
response (the evidence would be about the incident), and a pilot or beta
explicitly labelled as such (holding a system to a production bar before its
owners claim it is one is not a finding, it is a gotcha).

## 2. Getting permission, or deciding it is not needed

Prefer asking. A short note — what the harness is, what it would send, how
many requests, over what period, from what user agent, what would be
published and when — costs a day and changes the run from something done *to*
an agency into something done *with* one. Most of the value of this work is in
the agency acting on it, and an agency that first hears about an audit from a
blog post acts on the blog post, not the audit.

Permission is **required**, not optional, for anything adversarial. Sending
prompt-injection probes to a production government service is security
testing, whatever the intent, and doing it uninvited is the kind of thing that
ends careers and prosecutions. That splits the question set in two:

| Set | Contents | Requires written permission |
|---|---|---|
| Quality | Ordinary questions a member of the public would ask. Accuracy, grounding, citations, refusal of out-of-scope requests, multilingual, fairness across phrasing registers. | No, if the terms permit automated access |
| Adversarial | Injection probes, extraction attempts, anything in the `adversarial` suite. | **Yes, in writing, from someone with authority to give it** |

Run the quality set alone until the second column has a yes. The report must
then say plainly that the adversarial suite was **not run** — as a disabled
suite with a stated reason, never as a suite that passed.

## 3. Rate, load and robots discipline

The person on the other end of this is a public service with a budget. The
harness's bounds exist to be used, not to be defaults:

- **Announce yourself.** The default user agent is `plumbline/<version>`.
  Never disguise it, never rotate it, never claim to be a browser. If an
  operator wants to block the run, they should be able to.
- **One request at a time.** The recorder is single-threaded by construction.
  Do not run several configurations concurrently to save an afternoon.
- **`min_interval_seconds` at 2.0 or higher** for a first run against a real
  service, and slower for a small agency. A 200-item set at one request every
  two seconds is seven minutes of somebody's capacity; there is no deadline
  that justifies compressing it.
- **`max_items` set to the exact size of the question set**, so a mistake
  costs one refusal rather than a flood.
- **`retries = 0`.** A 429 or a 503 is an answer: the service is asking for
  less. Stop the run, do not retry into it.
- **Off peak, in the service's own time zone.** Weekday mornings are when
  people need the service.
- **One pass.** Re-running to get a cleaner number is both bad statistics and
  double the load. If the run has to be repeated, that is a new dated
  recording with its own manifest, and both are kept.
- **Check `robots.txt` even though it probably does not cover an API.**
  Recording its contents and the date in the run log costs nothing and settles
  arguments later.
- **Stop on anything unexpected.** An error page, a CAPTCHA, a rate-limit
  header, a redirect, an unfamiliar response shape. Plumbline already aborts
  by default and refuses redirects; the discipline is not to override that and
  try again.

## 4. What goes into the question set

- **No real personal data, ever.** Invented names, invented identifiers,
  invented addresses. The demo bundle's `.example.gov` habit exists for this
  reason. Never use a real person's details, including your own.
- **No transactional requests.** Do not ask a system to file, submit, cancel,
  book or change anything. Questions only.
- **Questions a member of the public would actually ask**, drawn from the
  agency's own published guidance so that a reference answer can be sourced
  and cited. An evaluation set invented from nothing measures the inventor.
- **Reference answers cited to public sources**, with the URL and the date
  read, in `sources.jsonl`. Every accuracy or grounding claim in the published
  report then rests on a document the reader can open, not on the auditor's
  belief.
- **A subject-matter reviewer for the translations**, and the unreviewed
  warning left visible where there is not one. Publishing a multilingual
  finding based on translations nobody qualified has read is the same
  fabrication the harness exists to catch, committed by the auditor.

## 5. Handling what comes back

The recording is now a file containing a live public system's output. Treat it
as sensitive until it has been read:

- **Read every response before committing anything.** A government chat system
  can emit personal data — another applicant's details, a case number, a staff
  member's direct line. If it does, that is the single most serious finding
  the run can produce, and it must be reported privately and **must not be
  committed to a public repository**, not even in a bundle that is
  hash-protected. Redaction after publication does not work.
- **Keep the recording, sealed, wherever it lives.** The manifest already
  carries the timestamp, the endpoint, the call shape and the question set's
  hash, which is what makes the run defensible later.
- **Log the request count, the start and end time, the user agent and any
  non-200 responses**, alongside the recording.
- **Delete nothing selectively.** If part of a recording cannot be published,
  publish none of the transcript and publish the scores and the method
  instead. A curated transcript is not evidence.

## 6. Disclosure, before publication

Nothing is published until the agency has had the report and a fair chance to
respond. Two tracks, because two kinds of finding are not the same thing:

**Quality findings** — a wrong policy number, an ungrounded answer, a
fabricated citation, a refusal in the wrong direction, an inaccessible
interface, a disparity between languages or registers.

1. Send the full report — machine-readable and human-readable — the question
   set, the harness commit, and the exact command, to the named contact.
2. Ask for acknowledgement within **5 business days**, and offer a call.
3. Give **45 calendar days** before publishing, extendable if they are
   working on it and asking.
4. Offer to re-run after a fix, for free, and publish the second result
   alongside the first if they want it.

**Security findings** — anything the adversarial suite catches: an injection
that changes behavior, an extraction that works, personal data emitted that
the prompt did not contain.

1. Follow the agency's published vulnerability disclosure policy if it has
   one. If it does not, use CISA's coordinated disclosure route.
2. **90 days**, not 45, and no publication of a working exploit at any point.
3. If the finding is active harm to the public — the system is disclosing
   other people's case data right now — the timeline is not the point. Report
   it immediately, by phone if necessary, and stay quiet until it is fixed.

In both tracks, correct anything the agency shows to be wrong, publish the
correction as prominently as the original, and say so.

## 7. What may and may not be published about a named agency

**May be published**

- The verdict, every suite's score, floor, confidence interval and **minimum
  detectable effect**, exactly as the report prints them. The MDE is not
  optional garnish: publishing a score without it invites a reader to believe
  a two-point difference means something.
- The dataset hash, the judge configuration hash, the harness commit and the
  recording timestamp, so a third party can reproduce the run.
- The question set and the target configuration, in full.
- Specific, checkable defects: "asked in English the system said the cap was
  $850; asked the same question in Spanish it said $1,200; the published
  guidance says $850, here is the link."
- That the system was recorded on a stated date, and that systems change.

**May not be published**

- Anything about the people who built or run it. Not names, not team
  structure, not competence, not motive. The instrument measures a system's
  output and has nothing to say about anybody's work ethic.
- Personal data of any kind that appears in a transcript, including anything
  that could be re-identified from a quoted fragment.
- A ranking, a league table, a grade, or a comparison against another agency.
  The floors are demonstration defaults; the question sets differ; and a
  league table converts a diagnostic instrument into a reputational weapon,
  which is the fastest way to make agencies stop answering the phone.
- A characterisation of the *system* as unsafe, biased or discriminatory on
  the strength of these suites. They are deterministic screens over a lexicon.
  A clean privacy pass means "no shipped pattern matched"; a harms pass means
  "none of the listed phrases appeared". Report what was measured.
- An exploit, or enough detail to reconstruct one, for a security finding.
- Anything at all before the disclosure window has run.

Three specific honesty obligations, because they are the ones most easily
skipped in a write-up:

1. **Say that the judge is lexical.** Token overlap punishes legitimate
   paraphrase. A low accuracy score against a real service is partly a
   statement about the metric, and the report has to say so where the number
   is, not in a footnote.
2. **Say what the refusal marker list covers.** Refusal detection is a
   substring match. Against a real service the list must be written from that
   service's own transcripts first, or the suite measures the list's coverage
   rather than the system's behavior. This bit the synthetic bundle; it will
   bite harder in the field. (See `DESIGN.md`, "What the refusal marker list
   cannot do".)
3. **Say the sample size out loud.** A first real run will be a couple of
   hundred items. Its MDEs will be in the range this repository's own demo
   reports, and a regression smaller than that could not have been detected.

## 8. Go / no-go checklist

Every line yes, in writing, before a single request:

- [ ] Target meets all of §1.
- [ ] Terms of use read and quoted in the run log; `robots.txt` recorded.
- [ ] A named contact exists and has been written to.
- [ ] Adversarial suite either disabled with a stated reason, or permitted in
      writing by someone with authority.
- [ ] Question set contains no real personal data and no transactional
      requests.
- [ ] Reference answers cited to dated public sources.
- [ ] Translations reviewed, or the unreviewed warning left visible.
- [ ] Rate bounds set: interval ≥ 2s, `max_items` = set size, `retries = 0`,
      off-peak, one pass.
- [ ] A stop rule agreed: what makes the run halt, and who can call it.
- [ ] A disclosure timeline agreed, and a named person who owns it.
- [ ] Agreement, before seeing the results, on what will be published if the
      findings are bad, and on what will be published if they are good.
- [ ] Repository owner has said yes.

The last line is the one this document exists to protect.

## 9. What Plumbline already gives you, and what it does not

Already handled, structurally:

- Recording and grading are separate commands, so the gate stays offline and
  the audit stays a pure function of committed bytes.
- Every bound has an explicit value and is recorded in the bundle manifest,
  along with the endpoint, the call shape, the question set's hash and the
  timestamp.
- Redirects are refused, credentials in URLs are refused, secrets come from
  the environment by name and never reach the manifest, a failed call aborts
  the recording rather than being scored as a bad answer, and `max_items`
  bounds a mistake.
- Every report carries a run id, the harness version and source digest, the
  seed, the dataset hash and the judge configuration hash, and no timestamp,
  so it is byte-reproducible.

Not handled, and not the harness's job:

- Reading anybody's terms of use.
- Deciding whether a question set is fair to the service.
- Knowing whether a response contains personal data that no pattern matches.
- Any of §6 or §7. Those are judgement, and they belong to a person.
