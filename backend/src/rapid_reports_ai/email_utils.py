"""Email utilities for sending magic links"""

import os
from typing import Optional

# Try Resend first, fallback to SMTP
try:
    import resend
    RESEND_AVAILABLE = True
except ImportError:
    RESEND_AVAILABLE = False

# Always import SMTP modules for fallback
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart


def send_magic_link_email(email: str, token: str, link_type: str = "password_reset") -> bool:
    """
    Send a magic link email via Resend (preferred) or SMTP fallback
    
    Args:
        email: Recipient email address
        token: Token to include in the link
        link_type: Type of link ('password_reset' or 'email_verification')
    
    Returns:
        True if sent successfully, False otherwise
    """
    frontend_url = os.getenv("FRONTEND_URL", "https://rad-flow.uk")
    
    # Determine link URL based on link type
    if link_type == "password_reset":
        subject = "Password Reset Request"
        url_path = "/reset-password"
    elif link_type == "email_verification":
        subject = "Verify Your Email Address"
        url_path = "/verify-email"
    else:
        print(f"Unknown link type: {link_type}")
        return False
    
    magic_url = f"{frontend_url}{url_path}?token={token}"
    
    # Debug: Check Resend availability and configuration
    print(f"\n{'='*60}")
    print(f"🔍 EMAIL DEBUG INFO")
    print(f"{'='*60}")
    print(f"Resend available: {RESEND_AVAILABLE}")
    resend_api_key = os.getenv("RESEND_API_KEY")
    print(f"RESEND_API_KEY set: {bool(resend_api_key)}")
    if resend_api_key:
        print(f"RESEND_API_KEY length: {len(resend_api_key)}")
        print(f"RESEND_API_KEY starts with 're_': {resend_api_key.startswith('re_')}")
    resend_from_email = os.getenv("RESEND_FROM_EMAIL")
    print(f"RESEND_FROM_EMAIL: {resend_from_email or 'Not set (will use default)'}")
    print(f"{'='*60}\n")
    
    # Try Resend first (preferred for production)
    if RESEND_AVAILABLE and resend_api_key:
        try:
            print(f"🚀 Attempting to send email via Resend...")
            # Set API key for Resend SDK v2
            resend.api_key = resend_api_key
            # Get from email, default to Resend's onboarding email if domain not configured
            from_email = os.getenv("RESEND_FROM_EMAIL", "RadFlow <onboarding@resend.dev>")
            print(f"📧 From email: {from_email}")
            print(f"📧 To email: {email}")
            
            # Create professional HTML email body
            html_body = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="utf-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
            </head>
            <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; line-height: 1.6; color: #333333; background-color: #f4f4f4; margin: 0; padding: 0;">
                <div style="max-width: 600px; margin: 0 auto; background-color: #ffffff; padding: 40px 20px;">
                    <div style="text-align: center; margin-bottom: 30px;">
                        <h1 style="color: #8B5CF6; margin: 0; font-size: 28px; font-weight: bold;">RadFlow</h1>
                    </div>
                    
                    <h2 style="color: #1a1a1a; font-size: 24px; margin-top: 0; margin-bottom: 20px;">{subject}</h2>
                    
                    <p style="color: #666666; font-size: 16px; margin-bottom: 30px;">
                        Click the button below to {subject.lower()}:
                    </p>
                    
                    <div style="text-align: center; margin: 30px 0;">
                        <a href="{magic_url}" 
                           style="background-color: #8B5CF6; color: #ffffff; padding: 14px 32px; 
                                  text-decoration: none; border-radius: 8px; display: inline-block; 
                                  font-weight: 600; font-size: 16px;">
                            {subject}
                        </a>
                    </div>
                    
                    <p style="color: #999999; font-size: 14px; margin-top: 30px; margin-bottom: 10px;">
                        Or copy and paste this link into your browser:
                    </p>
                    <p style="color: #8B5CF6; font-size: 12px; word-break: break-all; margin: 0;">
                        {magic_url}
                    </p>
                    
                    <hr style="border: none; border-top: 1px solid #e0e0e0; margin: 30px 0;">
                    
                    <p style="color: #999999; font-size: 12px; margin: 0;">
                        This link will expire in 1 hour.<br>
                        If you didn't request this, you can safely ignore this email.
                    </p>
                </div>
            </body>
            </html>
            """
            
            print(f"📤 Sending email via Resend API...")
            # Use the correct Resend SDK v2 API
            emails = resend.emails._emails.Emails()
            result = emails.send({
                "from": from_email,
                "to": [email],
                "subject": subject,
                "html": html_body,
            })
            
            print(f"✅ Resend API Response: {result}")
            print(f"✅ Email sent via Resend to {email}")
            print(f"📧 Email ID: {result.get('id', 'N/A')}")
            print(f"💡 Check your inbox and spam folder. You can also check delivery status at:")
            print(f"   https://resend.com/emails/{result.get('id', '')}")
            return True
            
        except Exception as e:
            import traceback
            print(f"❌ Resend failed with error:")
            print(f"   Error type: {type(e).__name__}")
            print(f"   Error message: {str(e)}")
            print(f"   Traceback:")
            traceback.print_exc()
            print(f"⚠️ Falling back to SMTP...")
            # Fall through to SMTP fallback
    
    # SMTP Fallback (for development or if Resend not configured)
    print(f"📬 Using SMTP fallback...")
    smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER")
    smtp_password = os.getenv("SMTP_PASSWORD")
    
    print(f"   SMTP_SERVER: {smtp_server}")
    print(f"   SMTP_PORT: {smtp_port}")
    print(f"   SMTP_USER set: {bool(smtp_user)}")
    print(f"   SMTP_PASSWORD set: {bool(smtp_password)}")
    
    if not smtp_user or not smtp_password:
        # In development, print the magic link to console instead of sending
        print(f"\n" + "="*60)
        print(f"📧 MAGIC LINK FOR {email}")
        print(f"="*60)
        print(f"Link Type: {link_type}")
        print(f"URL: {magic_url}")
        print(f"="*60 + "\n")
        return True
    
    try:
        # Create email message
        msg = MIMEMultipart()
        msg['From'] = smtp_user
        msg['To'] = email
        msg['Subject'] = subject
        
        # Create email body
        body = f"""
        <html>
        <body>
        <h2>{subject}</h2>
        <p>Click the link below to {subject.lower()}:</p>
        <p><a href="{magic_url}">{magic_url}</a></p>
        <p>This link will expire in 1 hour.</p>
        <p>If you didn't request this, you can safely ignore this email.</p>
        </body>
        </html>
        """
        
        msg.attach(MIMEText(body, 'html'))
        
        # Send email
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.send_message(msg)
        server.quit()
        
        print(f"✅ Email sent via SMTP to {email}")
        return True

    except Exception as e:
        print(f"❌ Failed to send email to {email}: {str(e)}")
        return False


# ---------------------------------------------------------------------------
# Admin notification on new sign-up
# ---------------------------------------------------------------------------

_ROLE_LABELS = {
    "consultant_radiologist": "Consultant radiologist",
    "registrar": "Registrar",
    "reporting_radiographer": "Reporting radiographer",
    "medical_student": "Medical student",
    "other_healthcare_professional": "Other healthcare professional",
    "other": "Other",
}


def _humanise_role(role: Optional[str]) -> str:
    if not role:
        return "Unknown"
    return _ROLE_LABELS.get(role, role)


def _send_plain_email(to: str, subject: str, body: str) -> bool:
    """Send a plain-text email via Resend, falling back to SMTP. Returns success."""
    resend_api_key = os.getenv("RESEND_API_KEY")
    if RESEND_AVAILABLE and resend_api_key:
        try:
            resend.api_key = resend_api_key
            from_email = os.getenv("RESEND_FROM_EMAIL", "RadFlow <onboarding@resend.dev>")
            emails = resend.emails._emails.Emails()
            emails.send({
                "from": from_email,
                "to": [to],
                "subject": subject,
                "text": body,
            })
            return True
        except Exception as exc:
            print(f"[admin-email] Resend failed: {exc}; falling back to SMTP")

    smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER")
    smtp_password = os.getenv("SMTP_PASSWORD")
    if not smtp_user or not smtp_password:
        print("[admin-email] No SMTP credentials; email not sent.")
        return False

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = smtp_user
        msg["To"] = to
        msg.attach(MIMEText(body, "plain"))
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.send_message(msg)
        server.quit()
        return True
    except Exception as exc:
        print(f"[admin-email] SMTP failed: {exc}")
        return False


def build_admin_signup_notification(user) -> tuple[str, str]:
    """Return (subject, body) for the admin notification email for a new user.

    `user` must have id, email, full_name, role, institution, signup_reason
    attributes. We import the signer lazily to avoid a circular import.
    """
    from .auth import sign_admin_action  # local import to avoid cycles

    role_label = _humanise_role(user.role)
    subject = f"[Radflow] New sign-up: {user.full_name or user.email} ({role_label})"

    api_base = os.getenv("ADMIN_API_BASE_URL", "https://radflow.app")
    approve_token = sign_admin_action(user.id, "approve")
    reject_token = sign_admin_action(user.id, "reject")
    approve_url = f"{api_base}/api/admin/approve?uid={user.id}&token={approve_token}"
    reject_url = f"{api_base}/api/admin/reject?uid={user.id}&token={reject_token}"

    body = (
        "A new user signed up for Radflow:\n"
        "\n"
        f"Name:        {user.full_name or '-'}\n"
        f"Email:       {user.email}\n"
        f"Role:        {role_label}\n"
        f"Institution: {user.institution or '-'}\n"
        "\n"
        "Why Radflow?\n"
        f"{user.signup_reason or '-'}\n"
        "\n"
        f"Approve:  {approve_url}\n"
        f"Reject:   {reject_url}\n"
    )
    return subject, body


def send_admin_signup_notification(user) -> bool:
    """Send the admin signup notification. Returns True on success."""
    admin_email = os.getenv("ADMIN_NOTIFICATION_EMAIL")
    if not admin_email:
        print("[admin-email] ADMIN_NOTIFICATION_EMAIL not set; skipping notification.")
        return False
    subject, body = build_admin_signup_notification(user)
    return _send_plain_email(admin_email, subject, body)
