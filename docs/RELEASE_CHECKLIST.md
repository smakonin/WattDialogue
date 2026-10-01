# Release checklist

The repository remains private during development. The paper's availability statement is written for its intended public-release version.

- [x] Use GNU GPL version 3 for the source code.
- [x] Provide a portable synthetic replay that requires no household data or API key.
- [x] Document local primary/backup key configuration and keep populated files out of Git.
- [x] Keep research datasets and generated private scoring products outside committed files.
- [ ] Confirm the clean-clone tests and GitHub Actions checks for the release commit.
- [ ] Freeze the model evaluation protocol, record failures and distinguish model results from deterministic checks.
- [ ] Select any actual replay sample for the hosted demo and establish its release permissions separately.
- [ ] Choose hosting, service-owned credentials, authentication and a spending policy for a shared online demo.
- [ ] Verify the paper's repository link, version and public availability before submission.
- [ ] Change repository visibility to public when the author decides it is ready to launch.

The manuscript and private research archives are maintained separately. The draft participant protocol and synthetic study website are included under `study/` for review; no study deployment or participant collection is enabled. The repository does not contain private keys, original recordings, the unpublished patent document or a completed occupant study.

- [ ] Before any study launch, review the included consent/protocol, complete the hosting and collection design, and obtain the required institutional approval.
