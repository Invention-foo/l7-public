/* eslint-disable @typescript-eslint/no-explicit-any */

'use client'

import { useState } from 'react'
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { toast } from 'react-hot-toast'
import { walletService } from '@/services/wallet.service'

interface Exception {
  id: string
  user_id: string
  created_at: string
}

interface ExceptionsClientProps {
  initialExceptions: Exception[]
}

export function ExceptionsClient({ initialExceptions }: ExceptionsClientProps) {
  const [exceptionUser, setExceptionUser] = useState('')
  const [exceptions, setExceptions] = useState(initialExceptions)
  const [isLoading, setIsLoading] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')

  // Filter exceptions based on search query
  const filteredExceptions = exceptions.filter(exception =>
    exception.user_id.toLowerCase().includes(searchQuery.toLowerCase())
  )

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    // Only allow numeric input
    const value = e.target.value.replace(/\D/g, '')
    setExceptionUser(value)
  }

  const handleAddException = async () => {
    // Validate input
    if (!exceptionUser) {
      toast.error('Please enter a user ID')
      return
    }

    if (!/^\d+$/.test(exceptionUser)) {
      toast.error('User ID must be numeric')
      return
    }

    if (exceptions.some(e => e.user_id === exceptionUser)) {
      toast.error('This user is already in exceptions')
      return
    }

    setIsLoading(true)
    try {
      // Get the connected wallet address
      const walletAddress = walletService.getConnectedWallet()
      if (!walletAddress) {
        throw new Error('Wallet not connected')
      }
      
      console.log('Wallet address:', walletAddress)
      
      // Create a message to sign
      const timestamp = Date.now()
      const message = `Add exception for user ${exceptionUser} at timestamp ${timestamp}`
      
      console.log('Preparing to sign message:', message)
      
      // Check if ethereum object exists
      if (!window.ethereum) {
        throw new Error('Ethereum provider not found. Please make sure MetaMask is installed.')
      }
      
      console.log('Requesting signature...')
      
      // Request signature from wallet
      let signature
      try {
        signature = await (window.ethereum as any).request({
          method: 'personal_sign',
          params: [message, walletAddress]
        })
        console.log('Signature received:', signature)
      } catch (signError) {
        console.error('Signature error:', signError)
        throw new Error(`Failed to sign message: ${(signError as Error).message || 'User rejected signature'}`)
      }
      
      if (!signature) {
        throw new Error('Failed to get signature')
      }
      
      console.log('Sending request to API...')
      
      // Send the request with signature
      const response = await fetch('/api/exceptions/add-exception', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          walletAddress,
          userId: exceptionUser,
          signature,
          message,
          timestamp
        })
      })
      
      console.log('API response status:', response.status)
      
      const result = await response.json()
      console.log('API response:', result)
      
      if (!result.success) {
        throw new Error(result.message || 'Failed to add exception')
      }
      
      setExceptions([
        ...exceptions,
        {
          id: crypto.randomUUID(),
          user_id: exceptionUser,
          created_at: new Date().toISOString()
        }
      ])
      setExceptionUser('')
      toast.success('Exception added successfully')
    } catch (error) {
      console.error('Failed to add exception:', error)
      toast.error(`Failed to add exception: ${(error as Error).message || 'Please try again'}`)
    } finally {
      setIsLoading(false)
    }
  }

  const handleRemoveException = async (userId: string) => {
    setIsLoading(true)
    try {
      // Get the connected wallet address
      const walletAddress = walletService.getConnectedWallet()
      if (!walletAddress) {
        throw new Error('Wallet not connected')
      }
      
      // Create a message to sign
      const timestamp = Date.now()
      const message = `Remove exception for user ${userId} at timestamp ${timestamp}`
      
      // Request signature from wallet
      const signature = await (window.ethereum as any).request({
        method: 'personal_sign',
        params: [message, walletAddress]
      })
      
      // Send the request with signature
      const response = await fetch('/api/exceptions/remove-exception', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          walletAddress,
          userId,
          signature,
          message,
          timestamp
        })
      })
      
      const result = await response.json()
      
      if (!result.success) {
        throw new Error(result.message || 'Failed to remove exception')
      }
      
      setExceptions(exceptions.filter(e => e.user_id !== userId))
      toast.success('Exception removed successfully')
    } catch (error) {
      console.error('Failed to remove exception:', error)
      toast.error(`Failed to remove exception: ${(error as Error).message || 'Please try again'}`)
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <Card className="bg-gray-900 shadow-lg">
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle className="text-2xl font-bold text-gray-100">Exceptions</CardTitle>
        <div className="w-64">
          <Input
            type="text"
            placeholder="Search exceptions..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="bg-gray-800 text-gray-100 border-gray-700 focus:border-[#b829e3]"
          />
        </div>
      </CardHeader>
      <CardContent>
        <CardDescription className="text-gray-300 mb-4">
          Manage users exempt from bans and blacklists. 
          <br />
          <br />
          <span className="text-xs text-gray-400">
            Note: Only enter the numeric user ID, not the @username.
          </span>
        </CardDescription>
        <div className="flex space-x-2 mb-4">
          <Input
            type="text"
            placeholder="Add Telegram user ID"
            value={exceptionUser}
            onChange={handleInputChange}
            className="bg-gray-800 text-gray-100 border-gray-700 focus:border-blue-500"
            disabled={isLoading}
          />
          <Button 
            onClick={handleAddException} 
            className="bg-blue-600 hover:bg-blue-700 text-white transition-colors duration-200"
            disabled={isLoading}
          >
            Add
          </Button>
        </div>

        <div className="flex flex-wrap gap-2">
          {filteredExceptions.map((exception) => (
            <Badge 
              key={exception.id} 
              variant="secondary" 
              className="bg-gray-800 text-gray-200 p-2"
            >
              {exception.user_id}
              <button
                onClick={() => handleRemoveException(exception.user_id)}
                className="ml-2 text-gray-400 hover:text-gray-200 transition-colors duration-200"
                disabled={isLoading}
              >
                ×
              </button>
            </Badge>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}