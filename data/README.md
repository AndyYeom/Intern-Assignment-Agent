# data/

Blob storage for the running application (`STORAGE_ROOT`). Its layout mirrors
the S3 bucket that will replace it:

    resumes/<applicant reference>/<id>.pdf

Everything in here is written by the backend (uploads through `/apply`, and the
legacy import copying the historical resumes). It is not committed; the
database stores each file's key relative to this folder.

Structured data lives in PostgreSQL. Reference files the system reads are in
`resources/`; the historical file-based dataset is in `legacy/`.
