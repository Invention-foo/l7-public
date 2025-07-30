'use client'

import { useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Wallet, AlertCircle, CheckCircle, XCircle } from 'lucide-react'
import { useWallet } from '@/hooks/use-wallet'
import { useAppKit } from '@reown/appkit/react'
import { walletService } from '@/services/wallet.service'
import { Spinner } from '@/components/ui/spinner'

// SMITH token threshold
const SMITH_THRESHOLD = 250000;

export default function LoginForm() {
  const [error, setError] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [isCheckingBalance, setIsCheckingBalance] = useState(false)
  const [smithBalance, setSmithBalance] = useState<number | null>(null)
  const [formattedBalance, setFormattedBalance] = useState<string | null>(null)
  const [meetsThreshold, setMeetsThreshold] = useState<boolean | null>(null)
  const [userExists, setUserExists] = useState<boolean | null>(null)
  const [isCheckingConnection, setIsCheckingConnection] = useState(true)
  
  const router = useRouter()
  const { isConnected, address } = useWallet()
  const { open } = useAppKit()

  // Add this effect to check initial wallet connection
  useEffect(() => {
    // Log the connection state for debugging
    console.log('Wallet connection state:', { isConnected, address })
    
    // Set checking connection to false after a short delay
    // This gives time for the wallet state to be properly initialized
    const timer = setTimeout(() => {
      setIsCheckingConnection(false)
    }, 500)
    
    return () => clearTimeout(timer)
  }, [isConnected, address])

  // Check balance when wallet is connected
  useEffect(() => {
    const checkEligibility = async () => {
      if (isConnected && address) {
        setIsCheckingBalance(true);
        try {
          // Check if user exists and is eligible
          const { 
            userExists, 
            // eslint-disable-next-line @typescript-eslint/no-unused-vars
            isEligible, 
            balance, 
            formattedBalance, 
            meetsThreshold 
          } = await walletService.checkUserEligibility(address);
          
          setSmithBalance(balance);
          setFormattedBalance(formattedBalance);
          setMeetsThreshold(meetsThreshold);
          setUserExists(userExists);
          
          // Handle different scenarios
          if (userExists) {
            // User exists
            if (meetsThreshold) {
              // User exists and meets threshold - redirect to console
              setTimeout(() => {
                router.push('/admin-console');
              }, 3000);
            }
            // If user exists but doesn't meet threshold, just show the message
          } else {
            // User doesn't exist
            if (meetsThreshold) {
              // User doesn't exist but meets threshold - create account and redirect
              const accountCreated = await walletService.createUserAccountIfEligible(address);
              if (accountCreated) {
                setTimeout(() => {
                  router.push('/admin-console');
                }, 3000);
              }
            }
            // If user doesn't exist and doesn't meet threshold, just show the message
          }
        } catch (error) {
          console.error('Error checking eligibility:', error);
          setError('Failed to check SMITH token balance');
        } finally {
          setIsCheckingBalance(false);
        }
      }
    };
    
    if (!isCheckingConnection && isConnected && address) {
      checkEligibility();
    }
  }, [isConnected, address, router, isCheckingConnection]);

  const handleConnect = async () => {
    setError(null)
    setIsLoading(true)
    
    try {
      await open({ view: 'Connect' });
    } catch (error) {
      console.error('Wallet connection error:', error)
      if (error instanceof Error) {
        setError(error.message)
      } else {
        setError('Failed to connect wallet')
      }
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="flex items-center justify-center min-h-screen bg-gray-950 text-gray-100">
      <Card className="w-full max-w-md bg-gray-900 shadow-lg">
        <CardHeader className="space-y-1">
          <CardTitle className="text-2xl font-bold text-center text-neoguard-primary">Login to NeoGuard</CardTitle>
          <CardDescription className="text-center text-gray-400">
            Connect your wallet to access the admin console
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            {error && (
              <div className="bg-red-900/30 border border-red-500 text-red-300 p-3 rounded flex items-center">
                <AlertCircle className="mr-2 h-4 w-4" />
                <p className="text-sm">{error}</p>
              </div>
            )}
            
            {isCheckingConnection ? (
              <div className="bg-gray-800 p-4 rounded-lg flex items-center justify-center">
                <Spinner size={20} className="mr-2" />
                <p>Checking wallet connection...</p>
              </div>
            ) : isConnected && address ? (
              <div className="space-y-4">
                <div className="bg-gray-800 p-4 rounded-lg">
                  <p className="text-sm text-gray-400 mb-1">Connected Wallet</p>
                  <p className="font-mono text-gray-100 break-all">{address}</p>
                </div>
                
                {isCheckingBalance ? (
                  <div className="bg-gray-800 p-4 rounded-lg flex items-center justify-center">
                    <Spinner size={20} className="mr-2" />
                    <p>Checking SMITH token balance...</p>
                  </div>
                ) : smithBalance !== null ? (
                  <div className="bg-gray-800 p-4 rounded-lg">
                    <div className="flex justify-between items-center mb-2">
                      <p className="text-sm text-gray-400">SMITH Balance</p>
                      {meetsThreshold ? (
                        <span className="bg-green-900/30 text-green-400 text-xs px-2 py-1 rounded flex items-center">
                          <CheckCircle className="mr-1 h-3 w-3" /> Eligible
                        </span>
                      ) : (
                        <span className="bg-red-900/30 text-red-400 text-xs px-2 py-1 rounded flex items-center">
                          <XCircle className="mr-1 h-3 w-3" /> Not Eligible
                        </span>
                      )}
                    </div>
                    <p className="text-xl font-bold text-gray-100">{formattedBalance} SMITH</p>
                    
                    {meetsThreshold ? (
                      <div className="mt-4 bg-green-900/30 border border-green-700 text-green-300 p-3 rounded text-sm">
                        <CheckCircle className="inline-block mr-1 h-4 w-4" /> 
                        You meet the threshold! {userExists ? 'Welcome back! ' : ''}Redirecting to admin console...
                      </div>
                    ) : (
                      <div className="mt-4 bg-amber-900/30 border border-amber-700 text-amber-300 p-3 rounded text-sm">
                        <AlertCircle className="inline-block mr-1 h-4 w-4" />
                        You need at least {SMITH_THRESHOLD.toLocaleString()} SMITH tokens to access the admin console.
                        {userExists && (
                          <p className="mt-2">
                            Your account has been marked as ineligible until you meet the threshold.
                          </p>
                        )}
                        <a href="https://app.uniswap.org" target="_blank" rel="noopener noreferrer" className="block mt-2 text-amber-400 hover:underline">
                          Buy SMITH tokens →
                        </a>
                      </div>
                    )}
                  </div>
                ) : null}
              </div>
            ) : (
              <Button 
                onClick={handleConnect}
                disabled={isLoading}
                className="w-full bg-blue-600 hover:bg-blue-700 text-white transition-colors duration-200 h-12"
              >
                {isLoading ? (
                  <span className="flex items-center justify-center">
                    <Spinner size={20} className="mr-2" /> Connecting...
                  </span>
                ) : (
                  <span className="flex items-center justify-center">
                    <Wallet className="mr-2" size={20} /> Connect Wallet
                  </span>
                )}
              </Button>
            )}
            
            <p className="text-xs text-gray-400 text-center mt-4">
              By connecting your wallet, you agree to our Terms of Service and Privacy Policy.
            </p>
          </div>
        </CardContent>
      </Card>
    </div>
  )
} 