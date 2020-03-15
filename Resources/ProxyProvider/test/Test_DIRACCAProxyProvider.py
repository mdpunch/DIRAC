""" This is a test of the DIRACCAProxyProvider
"""

# pylint: disable=invalid-name,wrong-import-position,protected-access
import os
import re
import sys
import shutil
import commands
import unittest
import tempfile

from DIRAC.Core.Base.Script import parseCommandLine
parseCommandLine(ignoreErrors=True)

from DIRAC import gLogger, gConfig, S_OK, S_ERROR
from DIRAC.Core.Utilities.CFG import CFG
from DIRAC.Core.Security.X509Chain import X509Chain  # pylint: disable=import-error
from DIRAC.Resources.ProxyProvider.ProxyProviderFactory import ProxyProviderFactory


thisPath = os.path.dirname(os.path.abspath(__file__)).split('/')
rootPath = thisPath[:len(thisPath) - 3]
certsPath = os.path.join('/'.join(rootPath), 'Core/Security/test/certs')

testCAPath = os.path.join(tempfile.mkdtemp(dir='/tmp'), 'ca')
testCAConfigFile = os.path.join(testCAPath, 'openssl_config_ca.cnf')

diracTestCACFG = """
Resources
{
  ProxyProviders
  {
    DIRAC_CA
    {
      ProviderType = DIRACCA
      CertFile = %s
      KeyFile = %s
      Supplied = O, OU, CN
      DNOrder = O, OU, CN, emailAddress
      Optional = emailAddress
      OU = CA
      C = DN
      O = DIRACCA
    }
    DIRAC_CA_CFG
    {
      ProviderType = DIRACCA
      CAConfigFile = %s
    }
  }
}
""" % (os.path.join(certsPath, 'ca/ca.cert.pem'),
       os.path.join(certsPath, 'ca/ca.key.pem'),
       testCAConfigFile)


class DIRACCAProviderTestCase(unittest.TestCase):

  @classmethod
  def setUpClass(cls):
    cls.failed = False

    # Add configuration
    cfg = CFG()
    cfg.loadFromBuffer(diracTestCACFG)
    gConfig.loadCFG(cfg)

    shutil.copytree(os.path.join(certsPath, 'ca'), testCAPath)

    # Parse
    lines = []
    with open(testCAConfigFile, "r") as caCFG:
      for line in caCFG:
        if re.findall('=', re.sub(r'#.*', '', line)):
          # Ignore comments
          field = re.sub(r'#.*', '', line).replace(' ', '').rstrip().split('=')[0]
          # Put the right dir
          line = 'dir = %s #PUT THE RIGHT DIR HERE!\n' % (testCAPath) if field == 'dir' else line
        lines.append(line)
    # Write modified conf. file
    with open(testCAConfigFile, "w") as caCFG:
      caCFG.writelines(lines)

    # Result
    status, output = commands.getstatusoutput('ls -al %s' % testCAPath)
    if status:
      gLogger.error(output)
      exit()
    gLogger.debug('Test path:\n', output)

  def setUp(self):
    gLogger.debug('\n')
    if self.failed:
       self.fail(self.failed)

  def tearDown(self):
    pass

  @classmethod
  def tearDownClass(cls):
    if os.path.exists(testCAPath):
      shutil.rmtree(testCAPath)


class testDIRACCAProvider(DIRACCAProviderTestCase):

  def test_getProxy(self):
    """ Test 'getProxy' - try to get proxies for different users and check it
    """
    def check(proxyStr, proxyProvider, name):
      """ Check proxy

          :param str proxyStr: proxy as string
          :param str proxyProvider: proxy provider name
          :param str name: proxy name
      """
      proxyFile = os.path.join(testCAPath, proxyProvider + name.replace(' ', '') + '.pem')
      gLogger.info('Check proxy..')
      chain = X509Chain()
      result = chain.loadProxyFromString(proxyStr)
      self.assertTrue(result['OK'], '\n' + result.get('Message', 'Error message is absent.'))
      for result in [chain.getRemainingSecs(),
                     chain.getIssuerCert(),
                     chain.getPKeyObj(),
                     chain.getCertList(),
                     chain.getNumCertsInChain(),
                     chain.generateProxyToString(3600),
                     chain.generateProxyToFile(proxyFile, 3600),
                     chain.isProxy(),
                     chain.isLimitedProxy(),
                     chain.isValidProxy(),
                     chain.isVOMS(),
                     chain.isRFC()]:
        self.assertTrue(result['OK'], '\n' + result.get('Message', 'Error message is absent.'))

    for proxyProvider, log in [('DIRAC_CA', 'configuring only in DIRAC CFG'),
                               ('DIRAC_CA_CFG', 'read configuration file')]:
      gLogger.info('\n* Try proxy provider that %s..' % log)
      result = ProxyProviderFactory().getProxyProvider(proxyProvider)
      self.assertTrue(result['OK'], '\n' + result.get('Message', 'Error message is absent.'))
      ca = result['Value']

      gLogger.info('* Get proxy using FullName and Email of user..')
      for name, email, res in [('MrUser', 'good@mail.com', True),
                               ('MrUser_1', 'good_1@mail.com', True),
                               (False, 'good@mail.com', False),
                               ('MrUser', False, True)]:
        gLogger.info('\nFullName: %s' % name or 'absent', 'Email: %s..' % email or 'absent')
        # Create user DN
        result = ca.generateDN(FullName=name, Email=email)
        text = 'Must be ended %s%s' % ('successful' if res else 'with error',
                                       ': %s' % result.get('Message', 'Error message is absent.'))
        self.assertEqual(result['OK'], res, text)
        if not res:
          gLogger.info('Msg: %s' % (result['Message']))
        else:
          userDN = result['Value']
          gLogger.info('Created DN:', userDN)

          result = ca.getProxy(userDN)
          text = 'Must be ended %s%s' % ('successful' if res else 'with error',
                                         ': %s' % result.get('Message', 'Error message is absent.'))
          self.assertEqual(result['OK'], res, text)
          if not res:
            gLogger.info('Msg: %s' % (result['Message']))
          else:
            check(result['Value']['proxy'], proxyProvider, name)

      gLogger.info('\n* Get proxy using user DN..')
      for dn, name, res in [('/O=DIRAC/OU=DIRAC CA/CN=user_3/emailAddress=some@mail.org', 'user_3', True),
                            ('/O=Dirac/OU=DIRAC CA/CN=user/emailAddress=some@mail.org', 'user', True),
                            ('/O=Dirac/OU=Without supplied field/emailAddress=some@mail.org', 'not_suplied', False),
                            ('/O=Dirac/OU=DIRAC CA/CN=without email', 'no_email', True),
                            ('/some=bad/DN=', 'badDN', False),
                            ('/BF=Bad Field/O=IN/CN=DN', 'badField', False),
                            (False, 'absent', False)]:
        gLogger.info('\nDN:', dn or 'absent')
        try:
          result = ca.getProxy(dn)
        except Exception as e:
          self.assertFalse(res, e)
        text = 'Must be ended %s%s' % ('successful' if res else 'with error',
                                       ': %s' % result.get('Message', 'Error message is absent.'))
        self.assertEqual(result['OK'], res, text)
        if not res:
          gLogger.info('Msg: %s' % (result['Message']))
        else:
          check(result['Value']['proxy'], proxyProvider, name)


if __name__ == '__main__':
  suite = unittest.defaultTestLoader.loadTestsFromTestCase(DIRACCAProviderTestCase)
  suite.addTest(unittest.defaultTestLoader.loadTestsFromTestCase(testDIRACCAProvider))
  testResult = unittest.TextTestRunner(verbosity=2).run(suite)
  sys.exit(not testResult.wasSuccessful())
