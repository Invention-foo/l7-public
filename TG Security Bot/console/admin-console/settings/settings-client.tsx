/* eslint-disable @typescript-eslint/no-explicit-any */
'use client'

import { useState } from 'react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Switch } from "@/components/ui/switch"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Button } from "@/components/ui/button"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { toast } from 'react-hot-toast'
import { walletService } from '@/services/wallet.service'

interface Setting {
  id: string
  title: string
  description: string
  enabled: boolean
  disabled: boolean
}

interface CommunityInfo {
  address: string
  name: string
  telegram: string
  discord: string
  twitter: string
  project_type: string
  ticker: string
}

interface SettingsClientProps {
  initialSettings: Setting[]
  settingsId: string | null
  initialCommunityInfo: CommunityInfo | null
}

export function SettingsClient({ initialSettings, settingsId, initialCommunityInfo }: SettingsClientProps) {
  const [settings, setSettings] = useState<Setting[]>(initialSettings)
  const [isLoading, setIsLoading] = useState(false)
  const [communityInfo, setCommunityInfo] = useState<CommunityInfo>(
    initialCommunityInfo || {
      address: '',
      name: '',
      telegram: '',
      discord: '',
      twitter: '',
      project_type: '',
      ticker: ''
    }
  )
  const [isSavingCommunity, setIsSavingCommunity] = useState(false)

  const toggleSetting = async (id: string) => {
    const setting = settings.find(s => s.id === id)
    if (setting?.disabled || !settingsId) return

    setIsLoading(true)
    try {
      const newValue = !settings.find(s => s.id === id)?.enabled
      
      // Get the connected wallet address
      const walletAddress = walletService.getConnectedWallet()
      if (!walletAddress) {
        throw new Error('Wallet not connected')
      }
      
      // Check if ethereum object exists
      if (!window.ethereum) {
        throw new Error('Ethereum provider not found. Please make sure MetaMask is installed.')
      }
      
      // First request account access
      try {
        await (window.ethereum as any).request({ 
          method: 'eth_requestAccounts' 
        })
      } catch (accessError) {
        throw new Error(`Failed to access wallet: ${(accessError as Error).message || 'User rejected connection'}`)
      }
      
      // Create a message to sign
      const timestamp = Date.now()
      const message = `Update setting ${id} to ${newValue} at timestamp ${timestamp}`
      
      // Request signature from wallet
      let signature
      try {
        // Convert message to hex format as required by some wallets
        const msgHex = '0x' + Buffer.from(message).toString('hex')
        
        signature = await (window.ethereum as any).request({
          method: 'personal_sign',
          params: [msgHex, walletAddress]
        })
      } catch (signError) {
        throw new Error(`Failed to sign message: ${(signError as Error).message || 'User rejected signature'}`)
      }
      
      if (!signature) {
        throw new Error('Failed to get signature')
      }
      
      // Send the request with signature
      const response = await fetch('/api/settings/update-setting', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          walletAddress,
          settingsId,
          settingName: id,
          value: newValue,
          signature,
          message,
          timestamp
        })
      })
      
      const result = await response.json()
      
      if (!result.success) {
        throw new Error(result.message || 'Failed to update setting')
      }
      
      setSettings(settings.map(setting => 
        setting.id === id ? { ...setting, enabled: newValue } : setting
      ))
      toast.success('Setting updated successfully')
    } catch (error) {
      console.error('Failed to update setting:', error)
      toast.error(`Failed to update setting: ${(error as Error).message || 'Please try again'}`)
      // Revert the UI change if the API call failed
      setSettings([...settings])
    } finally {
      setIsLoading(false)
    }
  }

  const updateCommunityInfo = async () => {
    setIsSavingCommunity(true)
    try {
      // Get the connected wallet address
      const walletAddress = walletService.getConnectedWallet()
      if (!walletAddress) {
        throw new Error('Wallet not connected')
      }
      
      // Check if ethereum object exists
      if (!window.ethereum) {
        throw new Error('Ethereum provider not found. Please make sure MetaMask is installed.')
      }
      
      // First request account access
      try {
        await (window.ethereum as any).request({ 
          method: 'eth_requestAccounts' 
        })
      } catch (accessError) {
        throw new Error(`Failed to access wallet: ${(accessError as Error).message || 'User rejected connection'}`)
      }
      
      // Create a message to sign
      const timestamp = Date.now()
      const message = `Update community information at timestamp ${timestamp}`
      
      // Request signature from wallet
      let signature
      try {
        // Convert message to hex format as required by some wallets
        const msgHex = '0x' + Buffer.from(message).toString('hex')
        
        signature = await (window.ethereum as any).request({
          method: 'personal_sign',
          params: [msgHex, walletAddress]
        })
      } catch (signError) {
        throw new Error(`Failed to sign message: ${(signError as Error).message || 'User rejected signature'}`)
      }
      
      if (!signature) {
        throw new Error('Failed to get signature')
      }
      
      // Send the request with signature
      const response = await fetch('/api/settings/update-community-info', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          walletAddress,
          communityInfo,
          signature,
          message,
          timestamp
        })
      })
      
      const result = await response.json()
      
      if (!result.success) {
        throw new Error(result.message || 'Failed to update community information')
      }
      
      toast.success('Community information updated successfully')
    } catch (error) {
      console.error('Failed to update community information:', error)
      toast.error(`Failed to update community information: ${(error as Error).message || 'Please try again'}`)
    } finally {
      setIsSavingCommunity(false)
    }
  }

  const handleCommunityInfoChange = (field: keyof CommunityInfo, value: string) => {
    setCommunityInfo(prev => ({
      ...prev,
      [field]: value
    }))
  }

  return (
    <div className="space-y-6">
      <Card className="bg-gray-900 shadow-lg">
        <CardHeader>
          <CardTitle className="text-2xl font-bold text-gray-100">Settings</CardTitle>
          <CardDescription className="text-gray-300">Configure NeoGuard protection features</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="space-y-6">
            {settings.map(setting => (
              <div key={setting.id} className="flex items-center justify-between">
                <div>
                  <h3 className="text-lg font-medium text-gray-100">{setting.title}</h3>
                  <p className="text-sm text-gray-400">{setting.description}</p>
                </div>
                <Switch
                  checked={setting.enabled}
                  onCheckedChange={() => toggleSetting(setting.id)}
                  className="data-[state=checked]:bg-blue-500"
                  disabled={isLoading || setting.disabled || !settingsId}
                />
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      <Card className="bg-gray-900 shadow-lg">
        <CardHeader>
          <CardTitle className="text-2xl font-bold text-gray-100">Community Information</CardTitle>
          <CardDescription className="text-gray-300">
            Update your project&apos;s community details
          </CardDescription>
          <div className="mt-3 p-3 bg-blue-900/20 border border-blue-800/30 rounded-lg">
            <p className="text-sm text-blue-200 mb-2">This information is used to:</p>
            <ul className="text-sm text-blue-300 space-y-1">
              <li className="flex items-start">
                <span className="text-blue-400 mr-2">•</span>
                Add additional context for AthenaAI to moderate more effectively
              </li>
              <li className="flex items-start">
                <span className="text-blue-400 mr-2">•</span>
                <span className="text-gray-400">[Future]</span> Bot commands for Telegram users to get project information
              </li>
            </ul>
          </div>
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <Label htmlFor="contract-address" className="text-gray-200">Contract Address</Label>
                <Input
                  id="contract-address"
                  value={communityInfo.address}
                  onChange={(e) => handleCommunityInfoChange('address', e.target.value)}
                  placeholder="0x..."
                  className="bg-gray-800 border-gray-700 text-gray-100"
                />
              </div>
              <div>
                <Label htmlFor="project-name" className="text-gray-200">Project Name</Label>
                <Input
                  id="project-name"
                  value={communityInfo.name}
                  onChange={(e) => handleCommunityInfoChange('name', e.target.value)}
                  placeholder="Your Project Name"
                  className="bg-gray-800 border-gray-700 text-gray-100"
                />
              </div>
              <div>
                <Label htmlFor="ticker" className="text-gray-200">Ticker</Label>
                <Input
                  id="ticker"
                  value={communityInfo.ticker}
                  onChange={(e) => handleCommunityInfoChange('ticker', e.target.value)}
                  placeholder="TOKEN"
                  className="bg-gray-800 border-gray-700 text-gray-100"
                />
              </div>
              <div>
                <Label htmlFor="project-type" className="text-gray-200">Project Type</Label>
                <Select 
                  value={communityInfo.project_type} 
                  onValueChange={(value) => handleCommunityInfoChange('project_type', value)}
                >
                  <SelectTrigger className="bg-gray-800 border-gray-700 text-gray-100">
                    <SelectValue placeholder="Select project type" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="defi">DeFi</SelectItem>
                    <SelectItem value="nft">NFT</SelectItem>
                    <SelectItem value="gaming">Gaming</SelectItem>
                    <SelectItem value="dao">DAO</SelectItem>
                    <SelectItem value="infrastructure">Infrastructure</SelectItem>
                    <SelectItem value="meme">Meme</SelectItem>
                    <SelectItem value="ai">AI</SelectItem>
                    <SelectItem value="other">Other</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div>
                <Label htmlFor="telegram" className="text-gray-200">Telegram</Label>
                <Input
                  id="telegram"
                  value={communityInfo.telegram}
                  onChange={(e) => handleCommunityInfoChange('telegram', e.target.value)}
                  placeholder="@yourproject"
                  className="bg-gray-800 border-gray-700 text-gray-100"
                />
              </div>
              <div>
                <Label htmlFor="discord" className="text-gray-200">Discord</Label>
                <Input
                  id="discord"
                  value={communityInfo.discord}
                  onChange={(e) => handleCommunityInfoChange('discord', e.target.value)}
                  placeholder="discord.gg/yourproject"
                  className="bg-gray-800 border-gray-700 text-gray-100"
                />
              </div>
              <div className="md:col-span-2">
                <Label htmlFor="twitter" className="text-gray-200">Twitter</Label>
                <Input
                  id="twitter"
                  value={communityInfo.twitter}
                  onChange={(e) => handleCommunityInfoChange('twitter', e.target.value)}
                  placeholder="@yourproject"
                  className="bg-gray-800 border-gray-700 text-gray-100"
                />
              </div>
            </div>
            <div className="flex justify-end">
              <Button
                onClick={updateCommunityInfo}
                disabled={isSavingCommunity}
                className="bg-blue-600 hover:bg-blue-700"
              >
                {isSavingCommunity ? 'Saving...' : 'Save Community Information'}
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}