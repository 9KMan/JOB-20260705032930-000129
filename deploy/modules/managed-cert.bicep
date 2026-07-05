// CPA Document Intake — Managed SSL certificate for custom domain
// Only provisioned when `customDomain` parameter is set.

param namePrefix string
param location string
param hostname string
param environmentId string

resource managedCert 'Microsoft.App/managedEnvironments/managedCertificates@2024-03-01' = {
  name: '${namePrefix}-cert-${replace(hostname, '.', '-')}'
  location: location
  parent: managedEnvRef
  properties: {
    subjectName: hostname
    managedCertificateDomainControlValidation: {
      cloud: 'Public'
    }
  }
}

resource managedEnvRef 'Microsoft.App/managedEnvironments@2024-03-01' existing = {
  name: split(environmentId, '/')[8]
}

output certId string = managedCert.id