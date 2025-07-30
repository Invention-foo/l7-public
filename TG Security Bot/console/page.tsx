'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { walletService } from '@/services/wallet.service'

export default function Home() {
  const router = useRouter()
  const [isChecking, setIsChecking] = useState(true)

  useEffect(() => {
    const checkAuthAndRedirect = async () => {
      try {
        // Check if user is authenticated using your wallet service
        const isAuthenticated = walletService.isAuthenticated()
        
        if (isAuthenticated) {
          // Get user info to check eligibility
          const { isEligible } = walletService.getUserInfo()
          
          if (isEligible) {
            router.push('/admin-console')
          } else {
            router.push('/login')
          }
        } else {
          router.push('/login')
        }
      } catch (error) {
        console.error('Error checking authentication:', error)
        router.push('/login')
      } finally {
        setIsChecking(false)
      }
    }

    checkAuthAndRedirect()
  }, [router])

  // Show a simple loading indicator while checking
  if (isChecking) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <p>Loading...</p>
      </div>
    )
  }

  return null
} 