from django.core import mail
from django.conf import settings

from django.test.runner import DiscoverRunner


class TestSuiteRunner(DiscoverRunner):
    """
    Just resets EMAIL_BACKEND to whatever was specified in settings.
    """
    
    def setup_test_environment(self, **kwargs):
        super(TestSuiteRunner, self).setup_test_environment(**kwargs)
        mail._original_email_backend = settings.EMAIL_BACKEND
        settings.EMAIL_BACKEND = 'djembe.backends.EncryptingTestBackend'
    
    def teardown_test_environment(self, **kwargs):
        super(TestSuiteRunner, self).teardown_test_environment(**kwargs)
        settings.EMAIL_BACKEND = mail._original_email_backend
