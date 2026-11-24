# Privacy policy

tidyinbox is an open-source program that runs on your own computer. There is no tidyinbox server, account or company behind it: every copy is run by its own user, with that user's own Google app.

## What it accesses

With your permission (Google's `gmail.modify` scope), tidyinbox:

- runs the Gmail searches written in your `rules.toml`, on Google's side;
- reads the **From** and **Subject** headers of 3 sample messages per rule, to show you what a rule catches;
- reads the **From** header of up to 300 messages when you run `senders`, to count who sends the mail that stays;
- reads your Gmail labels, creates the labels your rules name, and adds or removes labels on messages (moving mail out of the inbox and back).

It does not download message bodies or attachments. It does not send, and it never deletes mail.

## Where your data goes

Nowhere but between your computer and Google's Gmail API. tidyinbox has no analytics and no telemetry, and it shares nothing with third parties.

## What it stores

- The sign-in key (an OAuth refresh token, with your app's client ID and secret) is kept in your operating system's key store.
- Your rules are kept in a local file, `rules.toml`.

Nothing else is kept. Headers shown on screen are not saved.

## Removing it

Run `python tidyinbox.py logout` to delete the stored key, then remove the app's access at <https://myaccount.google.com/permissions>. Deleting the folder removes everything else.

## Google API Services

tidyinbox's use of information received from Google APIs adheres to the [Google API Services User Data Policy](https://developers.google.com/terms/api-services-user-data-policy), including the Limited Use requirements.

## Contact

Questions or concerns: open an issue at <https://github.com/makavli/tidyinbox/issues>.
