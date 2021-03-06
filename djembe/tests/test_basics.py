from django.core import mail
from django.core.mail import EmailMessage
from django.test import TestCase

from djembe.models import Identity
from djembe.tests import data
from djembe.exceptions import UnencryptableRecipients

from M2Crypto import BIO
from M2Crypto import SMIME
from M2Crypto import X509


class EncryptionTest(TestCase):
    def setUp(self):
        self.recipient1 = Identity.objects.create(
            certificate=data.RECIPIENT1_CERTIFICATE, key=data.RECIPIENT1_KEY
        )

        self.recipient2 = Identity.objects.create(
            certificate=data.RECIPIENT2_CERTIFICATE
        )

        self.list_member = Identity.objects.create(
            certificate=data.RECIPIENT1_CERTIFICATE, address="list@example.com"
        )

        self.list_member = Identity.objects.create(
            certificate=data.RECIPIENT2_CERTIFICATE, address="list@example.com"
        )

        self.text_template = "S/MIME multipart test %s"
        self.html_template = "<h1>S/MIME Test</h1><p>Message <strong>%s</strong></p>"

    def testAllTheThings(self):
        """
        Test the full scenario: multiple encrypted and plaintext recipients.

        Tests that multiple recipients can all read a message, and that
        recipients with no Identity records get plain text.
        """
        count = 1
        sender = Identity.objects.get(address="recipient1@example.com")
        recipients = [identity.address for identity in Identity.objects.all()]
        recipients.extend(["recipient3@example.com", "recipient4@example.com"])
        message = mail.EmailMultiAlternatives(
            self.text_template % count,
            self.text_template % count,
            sender.address,
            recipients,
        )
        message.attach_alternative(self.html_template % count, "text/html")
        message.send()

        backend = mail.get_connection()
        self.assertEqual(len(backend.messages), 2)

        #
        # verify the encryption and signature
        #
        s = SMIME.SMIME()

        # Load the sender's cert.
        x509 = X509.load_cert_string(data.RECIPIENT1_CERTIFICATE)
        sk = X509.X509_Stack()
        sk.push(x509)
        s.set_x509_stack(sk)

        # Load the sender's CA cert.
        st = X509.X509_Store()
        st.add_x509(x509)
        s.set_x509_store(st)

        # Decrypt the message as both encrypted recipients

        #
        # recipient 1
        #
        recipient1_cert = BIO.MemoryBuffer(data.RECIPIENT1_CERTIFICATE.encode("UTF-8"))
        recipient1_key = BIO.MemoryBuffer(data.RECIPIENT1_KEY.encode("UTF-8"))
        s.load_key_bio(recipient1_key, recipient1_cert)

        msg = BIO.MemoryBuffer(backend.messages[1]["message"].encode("UTF-8"))
        p7, msg_data = SMIME.smime_load_pkcs7_bio(msg)
        out = s.decrypt(p7)

        # Verify the message
        msg = BIO.MemoryBuffer(out)
        p7, msg_data = SMIME.smime_load_pkcs7_bio(msg)
        verified_msg = s.verify(p7, msg_data)
        self.assertTrue(verified_msg)

        #
        # recipient 2
        #
        recipient2_cert = BIO.MemoryBuffer(data.RECIPIENT2_CERTIFICATE.encode("UTF-8"))
        recipient2_key = BIO.MemoryBuffer(data.RECIPIENT2_KEY.encode("UTF-8"))
        s.load_key_bio(recipient2_key, recipient2_cert)

        msg = BIO.MemoryBuffer(backend.messages[1]["message"].encode("UTF-8"))
        p7, msg_data = SMIME.smime_load_pkcs7_bio(msg)
        out = s.decrypt(p7)

        # Verify the message
        msg = BIO.MemoryBuffer(out)
        p7, msg_data = SMIME.smime_load_pkcs7_bio(msg)
        self.assertTrue(s.verify(p7, msg_data))

        # verify that the plaintext also got through
        msg = BIO.MemoryBuffer(backend.messages[1]["message"].encode("UTF-8"))

    def testEncryptedDeliveryProblem(self):
        subject = "No! Not the radio!"
        body = "10-4 good buddy!"
        sender = "breakerbreaker@example.com"
        recipient = "recipient1@example.com"

        try:
            mail.send_mail(subject, body, sender, [recipient])
            self.fail("Unless you're four-wheeling, CB radio is a problem.")
        except ValueError:
            pass

    def testIdentityInstance(self):
        self.assertEqual(
            "C6:AF:98:41:75:D4:10:E9:BE:0A:5C:D8:7F:0E:6F:BB:A7:E1:B0:0E",
            self.recipient1.fingerprint,
        )

    def testMixedMessages(self):
        message1 = mail.message.EmailMessage(
            subject="This is a poison message.",
            body="And will cause an exception.",
            from_email="breakerbreaker@example.com",
            to=["somebody@example.com", "recipient1@example.com"],
        )

        backend = mail.get_connection()

        try:
            backend.send_messages([message1])
            self.fail("Poison message should have thrown an exception.")
        except ValueError:
            pass

    def testNoMessageToEncrypt(self):
        backend = mail.get_connection()
        try:
            backend.encrypt("recipient1@example.com", ["recipient2@example.com"], "")
            self.fail(
                "Lack of recipients should have raised an exception from encrypt method."
            )
        except ValueError:
            pass

    def testNoMessages(self):
        backend = mail.get_connection()
        sent = backend.send_messages([])
        self.assertEqual(0, sent)

    def testNoRecipientsToEncrypt(self):
        backend = mail.get_connection()
        try:
            backend.encrypt("recipient1@example.com", [], "")
            self.fail(
                "Lack of recipients should have raised an exception from encrypt method."
            )
        except ValueError:
            pass

    def testPlainTextDeliveryProblem(self):
        subject = "This is a poison message."
        body = "And will cause an exception."
        sender = "breakerofthings@example.com"
        recipient = "deadletteroffice@example.com"

        try:
            mail.send_mail(subject, body, sender, [recipient])
            self.fail("Poison message should have thrown an exception.")
        except ValueError:
            pass

    def testSenderIdentity(self):
        backend = mail.get_connection()

        # should get an error with no address
        try:
            sender = backend.get_sender_identity("")
            self.fail("Lack of sender address should have raised an exception")
        except ValueError:
            pass

        # a single valid sender should return a valid Identity
        sender_address = "multisender@example.com"
        Identity.objects.create(
            certificate=data.RECIPIENT1_CERTIFICATE,
            key=data.RECIPIENT1_KEY,
            address=sender_address,
        )
        sender = backend.get_sender_identity(sender_address)
        self.assertTrue(sender is not None)
        self.assertEqual(sender.address, sender_address)

        # No Identity should be returned when more than one is found with a
        # given address
        Identity.objects.create(
            certificate=data.RECIPIENT1_CERTIFICATE,
            key=data.RECIPIENT1_KEY,
            address=sender_address,
        )
        sender = backend.get_sender_identity(sender_address)
        self.assertTrue(sender is None)

    def testDisabledPlaintextFallback(self):
        subject = 'Multiple recipients'
        body = "Some recipients have Identities"
        sender = "sender@example.com"
        recipients = ["recipient1@example.com", "recipient3@example.com"]

        with self.settings(DJEMBE_PLAINTEXT_FALLBACK=True):
            messages_sent = mail.send_mail(subject, body, sender, recipients, fail_silently=True)
            self.assertEqual(2, messages_sent)

        with self.settings(DJEMBE_PLAINTEXT_FALLBACK=False):
            messages_sent = mail.send_mail(subject, body, sender, recipients, fail_silently=True)
            self.assertEqual(1, messages_sent)

            try:
                mail.send_mail(subject, body, sender, recipients, fail_silently=False)
                self.fail('Unencryptable recipients with DJEMBE_PLAINTEXT_FALLBACK=False ' +
                    'and fail_silently=False should have raised an exception')
            except UnencryptableRecipients as e:
                self.assertEqual(e.encrypting_recipients, set(['recipient1@example.com']))
                self.assertEqual(e.plaintext_recipients, set(['recipient3@example.com']))

    def testInvalidDateCert(self):
        from datetime import date, timedelta

        recipient_valid = 'valid@example.com'
        recipient_expired = 'expired@example.com'
        recipient_not_yet_valid = 'notyetvalid@example.com'
        today = date.today()
        backend = mail.get_connection()

        Identity.objects.create(
            certificate=data.RECIPIENT1_CERTIFICATE,
            address=recipient_valid,
            not_before = today - timedelta(days=2),
            not_after = today + timedelta(days=2),
        )
        Identity.objects.create(
            certificate=data.RECIPIENT1_CERTIFICATE,
            address=recipient_expired,
            not_before = today - timedelta(days=4),
            not_after = today - timedelta(days=2),
        )
        Identity.objects.create(
            certificate=data.RECIPIENT1_CERTIFICATE,
            address=recipient_not_yet_valid,
            not_before = today + timedelta(days=2),
            not_after = today + timedelta(days=4),
        )

        email_message = EmailMessage(
            'subject',
            'body',
            'sender@example.com',
            [recipient_valid, recipient_expired, recipient_not_yet_valid],
        )

        with self.settings(DJEMBE_VALIDATE_DATES=False):
            encrypting_identities, encrypting_recipients, plaintext_recipients = backend.analyze_recipients(email_message)
            self.assertEqual(encrypting_recipients, set([recipient_valid, recipient_expired, recipient_not_yet_valid]))

        with self.settings(DJEMBE_VALIDATE_DATES=True):
            encrypting_identities, encrypting_recipients, plaintext_recipients = backend.analyze_recipients(email_message)
            self.assertEqual(encrypting_recipients, set([recipient_valid]))
            self.assertEqual(plaintext_recipients, set([recipient_expired, recipient_not_yet_valid]))
