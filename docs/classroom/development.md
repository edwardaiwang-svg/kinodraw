# Classroom developer build

There is no public Chrome Web Store install link. The repository contains the
extension source, not a claim of an accepted production install. The extension
requires Chrome 124 or later. A raw checkout lacks generated `vendor/` and
`assets/` dependencies and cannot be loaded as a finished extension.

From the source checkout, with Node/npm and the existing Python environment:

```sh
cd edu
npm ci
PYTHON=/absolute/path/to/existing/python node tools/build.mjs
npm test
```

The build creates `edu/extension/vendor/` and `edu/extension/assets/`. Retain that
built directory and the build/test results. Only after the build succeeds, open
`chrome://extensions`, enable **Developer mode**, choose **Load unpacked**, and
select that built `edu/extension` folder. This is a developer testing route, not
Store distribution. The source manifest pins a development extension identity;
a Store build assigns another identity. Do not assume OAuth redirects carry over.

The extension's first video can download voice and picture models. Google sign-in,
Drive upload and Classroom posting are separate actions: use only the verified
teacher account and follow the repository's OAuth setup guide. A local build or
mocked test does not prove those live services are configured or production-ready.

See `edu/README.md` in the source checkout for OAuth setup and focused test
commands, and the shipped [privacy policy](privacy.html).
No build, browser installation, account login, upload or publication is performed
by these instructions or by the local gallery helper.

## Dated local load check

On 2026-10-06, a retained development package for source snapshot `773cbe4`
(version `0.1.0`) loaded in a fresh Chromium profile: its service worker started
and its welcome page opened. The package used existing generated `vendor/` and
`assets/` dependencies rather than a fresh regeneration. External network access
was blocked; Google sign-in, video synthesis, upload and Classroom posting were
not exercised. This establishes unpacked loading only.

![The actual locally loaded Classroom welcome page](development-welcome.png)
