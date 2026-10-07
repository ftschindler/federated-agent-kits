# Setting up the release pipeline

Four things in this repository's release have to be done by hand, once, by somebody with
admin on it. They are not code, they cannot be put in a workflow, and three of the four fail
loudly while the fourth fails in a way that looks like a permissions bug.

This page is the checklist. [T1](../IMPLEMENTATION.md#t1---the-package-the-cli-frame-and-ci)
owns it: a release pipeline that cannot push is not a release pipeline.

## 1. The required check on `main`

The ruleset protecting `main` currently requires one check, `🩺 (run governance checks)`,
because a required check that never reports blocks every merge and there was nothing else
reporting yet.

Once `.github/workflows/tests.yml` has run on one pull request, add `🛠 (Tests)` to the same
ruleset, and `🧪 (publish a rehearsal and install it)` alongside it.

`🛠 (Tests)` is the aggregate job, and that exact name, not the matrix jobs beneath it. It is the aggregate job, it has a fixed name, and it
fails unless every matrix job succeeded. The matrix jobs are named after the axis they ran on
(`🛠 (Tests, unit, ubuntu-latest)` and so on), so requiring one of those directly means
editing the rule every time the matrix changes. Worse, a matrix job that stops being produced
does not fail the rule: it silently stops being required.

The rehearsal job is safe to require even though a pull request from a fork cannot upload
anything: it still builds and checks the distribution, reports success, and says in a warning
annotation that it did not upload.

## 2. The release app

The release job pushes a version commit and a tag straight to `main`, which requires a pull
request. The token a job is handed by default cannot do that: it is deliberately not allowed
to bypass rules, which is the right default everywhere except here.

So, in order:

1. Create a GitHub App. One permission: **Repository permissions > Contents > Read and
   write**. No account permissions, no events, no webhook.
2. Install it on this repository only.
3. Generate a private key for it, and add two repository secrets:
   `RELEASE_APP_CLIENT_ID` (the client id from the app's settings page, not the numeric app
   id) and `RELEASE_APP_PRIVATE_KEY` (the whole `.pem`, including both `-----BEGIN` and
   `-----END` lines).
4. **Add the app to the bypass list of the ruleset protecting `main`.**

Step 4 is not a permission, is the one that gets forgotten, and is the reason this page
exists. Without it the job mints a valid token, pushes, and is declined by the ruleset. The
error says nothing about bypass lists.

## 3. Trusted publishing, on both indexes but not for the same thing

Two publishers, matched on two different workflow filenames, because that is what keeps them
apart. `release.yml` can reach PyPI and runs only on a push to `main`. `rehearsal.yml` can
reach TestPyPI and runs only on a pull request. A rehearsal that could authenticate as the
release would not be a rehearsal.

On [pypi.org](https://pypi.org/manage/account/publishing/):

| Field | Value |
| --- | --- |
| PyPI project name | `federated-agent-kits` |
| Owner | `ftschindler` |
| Repository name | `federated-agent-kits` |
| Workflow name | `release.yml` |
| Environment name | `pypi` |

And on [test.pypi.org](https://test.pypi.org/manage/account/publishing/), the same but for
the other workflow:

| Field | Value |
| --- | --- |
| PyPI project name | `federated-agent-kits` |
| Owner | `ftschindler` |
| Repository name | `federated-agent-kits` |
| Workflow name | `rehearsal.yml` |
| Environment name | `testpypi` |

Then create the two repository environments, `pypi` and `testpypi`. It needs no secrets: trusted publishing
exchanges the workflow's OIDC token for a short-lived upload token, so there is no API token
to leak, rotate or forget.

```sh
gh api --method PUT repos/ftschindler/federated-agent-kits/environments/pypi
gh api --method PUT repos/ftschindler/federated-agent-kits/environments/testpypi
```

The environment name has to match on both sides, and it names the GitHub environment rather
than the index. A mismatch is rejected at upload time with a message about an invalid claim,
which reads like a bug in the action.

## 4. The first publish

Label the pull request that lands this `minor`, and merge it. The release job works out the
next version, writes it into `pyproject.toml`, builds, checks, publishes, and only then
commits and tags.

An unpublished package is an untested release pipeline, which is why this happens at the end
of T1 rather than at the end of T12. The first real publish is the one that finds the
misconfigured name, the missing classifier and the trusted-publisher mismatch, and it is
much cheaper to find those on a package that does nothing yet.

Confirm it from a machine that has never seen this repository:

```sh
uvx --from federated-agent-kits akit --help
```

## The labels

Every pull request carries exactly one of `major`, `minor`, `patch`, `no-release`, and the
`🏷 (the pull request says how big it is)` job refuses one that does not. Create the four
labels before the first pull request, or the first one cannot be merged.

- `major`: a setup that works stops working.
- `minor`: something new.
- `patch`: a fix.
- `no-release`: nothing that ships, such as CI or documentation about the repository itself.
