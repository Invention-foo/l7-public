/* eslint-disable @typescript-eslint/no-explicit-any */
'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { walletService } from '@/services/wallet.service';
import { MessagesWrapper } from './messages-wrapper';

export default function MessagesPage() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [initialLogs, setInitialLogs] = useState<any[]>([]);
  const [chatId, setChatId] = useState('');
  const [teamMemberIds, setTeamMemberIds] = useState<Set<string>>(new Set());
  const [blacklistedUserIds, setBlacklistedUserIds] = useState<Set<string>>(new Set());
  const router = useRouter();
  
  useEffect(() => {
    async function fetchInitialData() {
      try {
        // Check if wallet is connected
        const connectedWallet = walletService.getConnectedWallet();
        
        if (!connectedWallet) {
          // No wallet connected, redirect to login
          router.push('/login');
          return;
        }
        
        // Fetch messages data
        const response = await fetch(`/api/messages/get-messages?walletAddress=${connectedWallet}&limit=50`);
        const result = await response.json();
        
        if (!result.success) {
          throw new Error(result.message || 'Failed to fetch messages');
        }
        
        // Extract data
        const { 
          messages, 
          teamMemberIds: teamIds, 
          blacklistedUserIds: blacklistIds, 
          chatId: userChatId 
        } = result.data;
        
        // Process messages
        const processedLogs = messages.map((msg: any) => ({
          user: extractUsername(msg.athena_secure_tg_logs.content),
          userId: msg.athena_secure_tg_logs.user_id,
          message: msg.message_text,
          timestamp: msg.created_at,
          id: msg.id,
          isTeamMember: teamIds.includes(msg.athena_secure_tg_logs.user_id),
          isBlacklisted: blacklistIds.includes(msg.athena_secure_tg_logs.user_id)
        }));
        
        setInitialLogs(processedLogs);
        setChatId(userChatId);
        setTeamMemberIds(new Set(teamIds));
        setBlacklistedUserIds(new Set(blacklistIds));
      } catch (err) {
        console.error('Error fetching messages:', err);
        setError('Failed to load messages. Please try again.');
      } finally {
        setLoading(false);
      }
    }
    
    fetchInitialData();
  }, [router]);
  
  function extractUsername(content: string): string {
    // Check if it's a bot-sent message
    if (content.startsWith('Bot sent message:')) {
      return 'NeoGuard'
    }
    
    // Regular user message
    const match = content.match(/Message received in group by (.+)/)
    return match ? match[1] : 'Unknown User'
  }
  
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
  
  return (
    <MessagesWrapper 
      initialLogs={initialLogs}
      chatId={chatId}
      teamMemberIds={teamMemberIds}
      blacklistedUserIds={blacklistedUserIds}
    />
  );
}