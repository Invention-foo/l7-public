'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { walletService } from '@/services/wallet.service';
import { SettingsClient } from './settings-client';

export default function SettingsPage() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [settings, setSettings] = useState<any[]>([]);
  const [settingsId, setSettingsId] = useState<string | null>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [communityInfo, setCommunityInfo] = useState<any>(null);
  const router = useRouter();
  
  useEffect(() => {
    async function fetchSettingsData() {
      try {
        // Check if wallet is connected
        const connectedWallet = walletService.getConnectedWallet();
        
        if (!connectedWallet) {
          // No wallet connected, redirect to login
          router.push('/login');
          return;
        }
        
        // Fetch settings data
        const response = await fetch(`/api/settings/get-settings?walletAddress=${connectedWallet}`);
        const result = await response.json();
        
        if (!result.success) {
          throw new Error(result.message || 'Failed to fetch settings');
        }
        
        setSettings(result.data.settings);
        setSettingsId(result.data.settingsId);
        setCommunityInfo(result.data.communityInfo);
      } catch (err) {
        console.error('Error fetching settings:', err);
        setError('Failed to load settings. Please try again.');
      } finally {
        setLoading(false);
      }
    }
    
    fetchSettingsData();
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
  
  return <SettingsClient initialSettings={settings} settingsId={settingsId} initialCommunityInfo={communityInfo} />;
}