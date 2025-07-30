/* eslint-disable @typescript-eslint/no-explicit-any */
'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { walletService } from '@/services/wallet.service';
import { ExceptionsClient } from './exceptions-client';

export default function ExceptionsPage() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [exceptions, setExceptions] = useState<any[]>([]);
  const [chatId, setChatId] = useState(''); 
  const router = useRouter();
  
  useEffect(() => {
    async function fetchExceptionsData() {
      try {
        // Check if wallet is connected
        const connectedWallet = walletService.getConnectedWallet();
        
        if (!connectedWallet) {
          // No wallet connected, redirect to login
          router.push('/login');
          return;
        }
        
        // Fetch exceptions data
        const response = await fetch(`/api/exceptions/get-exceptions?walletAddress=${connectedWallet}`);
        const result = await response.json();
        
        if (!result.success) {
          throw new Error(result.message || 'Failed to fetch exceptions');
        }
        
        setExceptions(result.data.exceptions);
        setChatId(result.data.chatId);
      } catch (err) {
        console.error('Error fetching exceptions:', err);
        setError('Failed to load exceptions. Please try again.');
      } finally {
        setLoading(false);
      }
    }
    
    fetchExceptionsData();
  }, [router]);
  
  if (loading) {
    return (
      <div className="flex justify-center items-center min-h-screen">
        <div className="animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-blue-500"></div>
      </div>
    );
  }
  
  if (error) {
    return (
      <div className="container mx-auto px-4 py-8">
        <div className="bg-red-100 p-4 rounded-md text-red-800 mb-4">
          {error}
        </div>
        <button
          onClick={() => router.push('/admin-console')}
          className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700"
        >
          Back to Admin Console
        </button>
      </div>
    );
  }
  
  if (!chatId) {
    return (
      <div className="container mx-auto px-4 py-8">
        <div className="bg-yellow-100 p-4 rounded-md text-yellow-800 mb-4">
          You need to set up your Telegram chat ID first.
        </div>
        <button
          onClick={() => router.push('/admin-console')}
          className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700"
        >
          Go to Setup
        </button>
      </div>
    );
  }
  
  return <ExceptionsClient initialExceptions={exceptions} />;
}