'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { walletService } from '@/services/wallet.service';
import { BansClient } from './bans-client';

export default function BansPage() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [banLogs, setBanLogs] = useState<any[]>([]);
  const router = useRouter();
  
  useEffect(() => {
    async function fetchBanData() {
      try {
        // Check if wallet is connected
        const connectedWallet = walletService.getConnectedWallet();
        
        if (!connectedWallet) {
          // No wallet connected, redirect to login
          router.push('/login');
          return;
        }
        
        // Fetch ban data
        const response = await fetch(`/api/bans/get-bans?walletAddress=${connectedWallet}`);
        const result = await response.json();
        
        if (!result.success) {
          throw new Error(result.message || 'Failed to fetch ban logs');
        }
        
        setBanLogs(result.data);
      } catch (err) {
        console.error('Error fetching ban logs:', err);
        setError('Failed to load ban logs. Please try again.');
      } finally {
        setLoading(false);
      }
    }
    
    fetchBanData();
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
  
  return <BansClient initialLogs={banLogs} />;
}