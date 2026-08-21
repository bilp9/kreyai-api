# KreyAI Linguist Partner Program

Internal operating guide for the KreyAI Linguist Partner Program. This document covers participant approval, complimentary license issuance, onboarding, support, feedback, and offboarding.

Do not commit participant lists, application exports, API keys, license keys, or other personal information to Git.

## Program purpose

The program invites a small group of working linguists to use KreyAI products in real professional workflows and share practical feedback. The initial cohort is limited to 10 participants so support can remain personal and findings can be acted on quickly.

This is a product-partner program, not an endorsement program. Participants are not required to publish reviews, promote KreyAI, or provide testimonials.

## Initial offer

- Complimentary permanent licenses for approved products.
- aTelier and Dekk are available in the initial program.
- Licenses are for the participant's own professional use and may not be sold or redistributed.
- aTelier partner licenses support activation on up to two computers.
- Products remain subject to their beta limitations and supported-platform requirements.
- Participation may be ended for license misuse or program abuse.

The participant agreement and public application copy should be professionally reviewed before the program is presented as a final legal offer.

## Eligibility and application

Collect only the information needed to evaluate and support the participant:

- Name
- Email address
- Operating system
- Working languages and specializations
- Relevant CAT or transcription experience
- Product or products requested
- Intended professional use
- Agreement to occasionally provide practical feedback

Do not request client documents, translation memories, recordings, or confidential work samples. KreyAI desktop products are designed for local work; partner administration should not weaken that privacy promise.

## Approval workflow

1. Review the application for a genuine professional-language use case.
2. Confirm the requested product supports the participant's computer.
3. Record the approval in a private administrative file or system.
4. Assign the participant to a cohort, initially `2026`.
5. Issue only the approved products.
6. Confirm that the welcome email was delivered.
7. Record the onboarding status without copying license keys into the participant tracker.

Suggested private tracker fields:

```text
name, email, cohort, products, approved_at, issued_at, onboarded_at, status, last_feedback_at, notes
```

## Production prerequisites

Before issuing the first external license, verify all of the following:

- The Linguist Partner API changes are deployed to production.
- The production API has the aTelier and Dekk signing secrets.
- The protected operations API key is available only to authorized operators.
- Transactional email delivery is configured and tested.
- The current aTelier build recognizes the partner license and its device allowance.
- The current Dekk build recognizes the `linguist_partner` plan.
- macOS downloads are signed and notarized.
- Windows downloads are signed and tested on a clean Windows 10 or Windows 11 computer.
- Installation, activation, deactivation, and update checks have been tested outside the development environment.

## Issue one participant

Set `KREYAI_OPS_API_KEY` in the shell without placing it in command history or committed files, then run:

```bash
python scripts/issue_linguist_partner.py \
  --email translator@example.com \
  --name "Translator Name" \
  --cohort 2026
```

The default issues aTelier and Dekk licenses and sends one welcome email. Issue only an approved product when appropriate:

```bash
python scripts/issue_linguist_partner.py \
  --email translator@example.com \
  --name "Translator Name" \
  --cohort 2026 \
  --products atelier
```

Supported product values are `atelier` and `dekk`.

## Issue a cohort from CSV

Create a private CSV outside the repository:

```csv
email,name
translator@example.com,Translator Name
```

Then run:

```bash
python scripts/issue_linguist_partner.py \
  --csv /secure/path/partners.csv \
  --cohort 2026
```

Retries are idempotent for the same email and cohort. The command does not print license keys. Newly generated keys are sent directly to the participant's email address.

To resend previously issued licenses without generating replacements:

```bash
python scripts/issue_linguist_partner.py \
  --email translator@example.com \
  --name "Translator Name" \
  --cohort 2026 \
  --resend
```

To record revocation for approved products:

```bash
python scripts/issue_linguist_partner.py \
  --email translator@example.com \
  --cohort 2026 \
  --products atelier,dekk \
  --revoke \
  --reason "Program access ended"
```

## Security rules

- Never send signing keys, operations API keys, or full participant lists through email or chat.
- Never paste license keys into issue trackers, logs, screenshots, or support tickets.
- Never return license keys from an operations API response.
- Keep temporary CSV files in an access-controlled location and remove them when the cohort is issued and verified.
- Use the production issuance service rather than generating keys on a personal computer.
- Treat participant email addresses and program notes as private administrative data.
- Do not request or collect client files as part of support or feedback unless a separate, explicit secure-support process has been approved.

## Welcome and onboarding

The welcome message should contain:

- The participant's approved product licenses
- Official download links
- Installation and activation steps
- Supported operating systems
- A concise local-data and privacy explanation
- Known beta limitations that affect normal use
- The support address
- The feedback form or feedback email

For the initial pilot, follow up personally after installation. Confirm that the participant can download, install, activate, open a sample project or file, and find support.

## Feedback process

Allow informal feedback by email and provide a short structured form for reproducible findings. Ask:

- What were you trying to accomplish?
- What worked well?
- Where did the workflow become confusing or slow?
- Did anything interrupt or endanger the work?
- Did you trust the output and data handling?
- What would make the product useful enough for regular professional work?

Do not ask participants to upload confidential client material. When a reproducible file is necessary, request a sanitized or synthetic sample.

## Support and incident handling

When a participant reports a problem:

1. Record the product, version, operating system, and exact action that failed.
2. Ask for local application logs only after explaining what they contain.
3. Remove personal or client information before attaching logs to an issue.
4. Classify activation, data loss, export corruption, and privacy failures as high priority.
5. Confirm the resolution with the participant and update this runbook when the failure reveals a missing procedure.

## Resend, replacement, and revocation

The issuance command is idempotent: rerunning it does not create duplicate licenses. Use `--resend` to send the existing key again without printing it. The protected operations API also records partner revocation by email, cohort, and product.

Operational rules:

- Do not manually create a second license to work around an email-delivery failure; use `--resend`.
- Do not edit signed license payloads or production records by hand.
- Investigate delivery through the transactional-email provider and recover the existing issuance through an approved administrative path.
- Escalate suspected compromise or misuse before changing activation state.

aTelier checks partner status through its activation service, removes active-device records on revocation, and rejects later activation. Dekk remains offline-verifiable: revocation is an administrative record that blocks resending, replacement, and continued program support, but it cannot remotely disable a key already stored on an offline computer. This distinction must remain explicit in participant and operator documentation.

## Pilot rollout

1. Issue internal test licenses and complete clean-install testing.
2. Invite two linguists first.
3. Observe onboarding, activation, normal work, updates, and feedback delivery.
4. Fix any serious workflow or data-safety failures.
5. Invite the remaining participants in small batches until the cohort reaches 10.

Do not invite the full cohort before the first two participants have successfully completed onboarding.

## Launch checklist

- [ ] Public program description approved
- [ ] Participant agreement and privacy language reviewed
- [ ] Application form tested
- [ ] Production issuance endpoint deployed
- [x] Secure resend and revocation workflows available
- [ ] Current aTelier partner-compatible build published
- [ ] Current Dekk partner-compatible build published
- [ ] macOS clean-install test passed
- [ ] Windows clean-install test passed
- [ ] Activation and deactivation tests passed
- [ ] Welcome email tested
- [ ] Onboarding page published
- [ ] Feedback form tested
- [ ] Private participant tracker prepared
- [ ] Two-person pilot completed
- [ ] Remaining invitations approved

## Completion criteria

The initial program is operating successfully when approved participants can install and activate their products without developer assistance, work without sending client data to KreyAI, receive updates and support, and provide feedback through a clear channel. Program records should identify who was approved and supported without exposing license keys or client information.
