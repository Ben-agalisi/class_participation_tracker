# Deployment: Django and Supabase

The project uses Django's ORM with Supabase PostgreSQL. The public student form and the staff admin are served by the same deployed app and database:

- Student form: `https://YOUR-DOMAIN/register/`
- Staff admin: `https://YOUR-DOMAIN/admin/`

## Supabase setup

1. Create a new project in Supabase.
2. Open the project dashboard and go to **Project settings** > **Database**.
3. Copy the PostgreSQL connection string from the **Connection string** section. Use the connection string that matches your runtime:
   - Local development or a server with standard PostgreSQL support: use the direct connection string.
   - Some hosting providers prefer the Session Pooler URI if direct SQL connections are blocked.
4. Make sure the URI includes SSL/TLS; Supabase requires it for secure access.
5. Paste the connection string into the environment variable `DATABASE_URL` on your machine or hosting platform.
6. Do not commit or publish the URL; it contains the database password and host information.
7. Install dependencies from `requirements.txt` and then set the rest of the environment variables before Django starts.

Example format for `DATABASE_URL`:

```text
DATABASE_URL=postgresql://postgres:YOUR_PASSWORD@db.your-project-ref.supabase.co:5432/postgres?sslmode=require
```

If you are testing locally in Windows PowerShell, set it like this:

```powershell
$env:DATABASE_URL="postgresql://postgres:YOUR_PASSWORD@db.your-project-ref.supabase.co:5432/postgres?sslmode=require"
```

If you are deploying on a platform such as Render, Railway, or a VPS, store the same value in the host's environment variables instead of hardcoding it in Django files.

This project reads `DATABASE_URL` directly from the environment in `class_participation/settings.py`, so the connection is configured outside the codebase.

## Required production environment variables

- `DATABASE_URL`: Supabase PostgreSQL URI from the dashboard.
- `DJANGO_SECRET_KEY`: a newly generated, private Django secret; do not reuse the development key.
- `DJANGO_DEBUG`: set to `false`.
- `DJANGO_ALLOWED_HOSTS`: comma-separated hostnames, for example `your-domain.example,app-host.example`.
- `DJANGO_CSRF_TRUSTED_ORIGINS`: full HTTPS origins, for example `https://your-domain.example`.
- `INDEX_ENCRYPTION_KEY`: a stable Fernet key; keep a protected backup. Generate one with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` and store it as a secret in the hosting platform.

The index encryption key must remain unchanged. Changing or losing it prevents decrypting the stored index numbers. Back up the key separately from the database backup.

## Migration and deployment commands

Run these from the project directory on the deployment host, with the environment variables configured:

```text
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py check --deploy
```

Then start the Django app using the hosting platform's supported WSGI/ASGI process command. Use the platform's HTTPS feature. The settings redirect HTTP to HTTPS and enable secure session and CSRF cookies when `DJANGO_DEBUG=false`.

The database migration `0004_encrypt_student_index_numbers` encrypts existing index numbers and stores keyed digests for uniqueness and exact-match lookup. For an existing SQLite database, do not copy the encrypted database to Supabase and use a different key. Either deploy a fresh Supabase database and have students register there, or arrange a controlled data migration using the same stable `INDEX_ENCRYPTION_KEY` before encrypting records.

## Data and access

Student records are stored in Supabase PostgreSQL. Django's `/admin/` remains staff-protected; create an admin account on the hosted database with `python manage.py createsuperuser`. Only the Django server should connect using the database URI. Never put the Supabase database password, Django secret, or index encryption key in browser code or public client configuration.

## Single staff account invitation

Only the superuser can create a staff invitation. After migrations and email configuration, run `python manage.py setup_mark_entry_role` once, then sign in at `/admin/` and add a **Staff invitation** with the approved person's email. The app emails a private one-time link that expires after `STAFF_INVITATION_TTL_HOURS` (default 24 hours). The invited person chooses their own username and password at `/staff-signup/?token=...`.

The claim is transactional and the database enforces a single staff seat. The new user is assigned only the configured `MARK_ENTRY_GROUP_NAME` role, which can view students/logs and award marks through the validated workflow. It cannot manage users, groups, or permissions. The superuser can see the account's username, email, status, role, and activity metadata, but never the password; Django stores only a salted password hash.

If the invitation email fails, the superuser can select the unused invitation in Admin and use **Resend selected unused invitation**. Deleting the staff user removes the seat; the superuser may then delete the old invitation and create another one. Students registering details at `/register/` do not create staff accounts.

## Password recovery

The staff login page links to **Forgot your password?**. Django sends a one-time reset link to the staff account email through the configured SMTP environment settings. The response is intentionally generic so the page does not reveal whether an email address belongs to an account. Configure `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS` or `EMAIL_USE_SSL`, and `DEFAULT_FROM_EMAIL` on the hosting platform. Test delivery before sharing the login with staff.

`check --deploy` is a useful baseline, not a penetration test or a guarantee that the application cannot be compromised. Keep Django and dependencies updated, use HTTPS, restrict staff accounts, configure backups, and monitor the hosting provider's logs.

## PythonAnywhere deployment notes

PythonAnywhere works well for this Django project if you set the environment variables in the dashboard and point the web app to the correct WSGI file.

1. Push your project to GitHub or upload it to a PythonAnywhere file system.
2. In the PythonAnywhere dashboard, open **Files** and upload the project folder.
3. Open **Consoles** and create a virtual environment.
4. Install dependencies with `pip install -r requirements.txt` inside the environment.
5. In the PythonAnywhere **Web** tab, create a new web app and choose **Manual configuration**.
6. Set the virtual environment path for the app.
7. Set the source code path to your project folder.
8. In the **Environment variables** section, add the same values you keep in the `.env` file, including:
   - `DATABASE_URL`
   - `DJANGO_SECRET_KEY`
   - `DJANGO_DEBUG`
   - `DJANGO_ALLOWED_HOSTS`
   - `DJANGO_CSRF_TRUSTED_ORIGINS`
   - `INDEX_ENCRYPTION_KEY`
   - `EMAIL_HOST`
   - `EMAIL_PORT`
   - `EMAIL_HOST_USER`
   - `EMAIL_HOST_PASSWORD`
   - `EMAIL_USE_TLS`
   - `DEFAULT_FROM_EMAIL`
9. Edit the WSGI file and point it to your Django project `wsgi.py` file.
10. Run `python manage.py migrate` in the PythonAnywhere Bash console.
11. Run `python manage.py createsuperuser` to create the admin account.
12. Run `python manage.py setup_mark_entry_role` once.
13. Visit the hosted `/admin/` URL, log in, and create the staff invitation.

PythonAnywhere expects a production-ready Django app, so set `DJANGO_DEBUG=false` before deploying publicly. Also add your domain or PythonAnywhere hostname to `DJANGO_ALLOWED_HOSTS` and `DJANGO_CSRF_TRUSTED_ORIGINS`.

If you are using Supabase, your `DATABASE_URL` value should still be the same as in the local `.env` file; only the host environment is different.
