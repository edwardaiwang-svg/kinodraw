// KinoDraw for Classroom: settings shared by every page of the extension.
// The Google OAuth client is a "Web application" client whose authorized redirect URI is
// https://<extension id>.chromiumapp.org/ (see edu/README.md, "Google sign-in").
export const CONFIG = {
  version: '0.1.0',
  dev: false,                                   // tests turn this on in a throwaway copy; never in a release
  cloudUrl: 'https://api.doodlecloud.org',      // KinoDraw Cloud: GPT-6 Luna director + server-side teacher check
  googleClientId: '292748984382-7uf3qe28fadngtjln2p6e77jgmmf87qi.apps.googleusercontent.com',
  scopes: [
    'https://www.googleapis.com/auth/classroom.courses.readonly',        // which classes you teach (the teacher check)
    'https://www.googleapis.com/auth/classroom.courseworkmaterials',     // post the video to Classwork
    'https://www.googleapis.com/auth/drive.file',                        // save the video to your Drive (only files this app made)
    'https://www.googleapis.com/auth/userinfo.email',                    // which Google account signed in
  ],
  voice: {                                      // the narrator: Kokoro-82M through HeadTTS, from a pinned revision
    model: 'onnx-community/Kokoro-82M-v1.0-ONNX-timestamped',
    revision: 'dd4401a9add81ac692d20e240d22ec9dda82cc29',
    voice: 'af_heart', dtypeWasm: 'q8', dtypeWebgpu: 'fp32',
  },
  embed: {                                      // doodle search: the exact model the desktop app uses (fastembed)
    model: 'Qdrant/bge-small-en-v1.5-onnx-Q',
    revision: '52398278842ec682c6f32300af41344b1c0b0bb2',
    file: 'model_optimized',
    sha256: '51f1bd0addd6e859e42c2c8021a5e5461385bb676a649f4b269aa445449f2431',
  },
};
