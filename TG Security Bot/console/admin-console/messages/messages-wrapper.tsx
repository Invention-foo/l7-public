'use client'

import { MessagesClient } from './messages-client'
import { walletService } from '@/services/wallet.service'

/* eslint-disable @typescript-eslint/no-explicit-any */

// eslint-disable-next-line @typescript-eslint/no-unused-vars
interface MessageLog {
    id: string
    message_text: string
    created_at: string
    athena_secure_tg_logs: {
      chat_id: string
      user_id: string
      content: string
    }
  }

  function extractUsername(content: string): string {
    // Check if it's a bot-sent message
    if (content.startsWith('Bot sent message:')) {
      return 'NeoGuard'
    }
    
    // Regular user message
    const match = content.match(/Message received in group by (.+)/)
    return match ? match[1] : 'Unknown User'
  }
  
  interface ProcessedMessageLog {
    user: string
    userId: string
    message: string
    timestamp: string
    id: string
    isTeamMember: boolean
    isBlacklisted: boolean
  }

interface MessagesWrapperProps {
  initialLogs: ProcessedMessageLog[]
  chatId: string
  teamMemberIds: Set<string>
  blacklistedUserIds: Set<string>
}

function processMessages(
  messages: any[], 
  teamMemberIds: Set<string>, 
  blacklistedUserIds: Set<string>
): ProcessedMessageLog[] {
  return messages.map(msg => ({
    user: extractUsername(msg.athena_secure_tg_logs.content),
    userId: msg.athena_secure_tg_logs.user_id,
    message: msg.message_text,
    timestamp: msg.created_at,
    id: msg.id,
    isTeamMember: teamMemberIds.has(msg.athena_secure_tg_logs.user_id),
    isBlacklisted: blacklistedUserIds.has(msg.athena_secure_tg_logs.user_id)
  }))
}

export function MessagesWrapper({ 
  initialLogs, 
  chatId, 
  teamMemberIds, 
  blacklistedUserIds 
}: MessagesWrapperProps) {
  const handleFetchMore = async (limit: number) => {
    const walletAddress = walletService.getConnectedWallet();
    if (!walletAddress) throw new Error('Wallet not connected');
    
    const response = await fetch(`/api/messages/get-messages?walletAddress=${walletAddress}&limit=${limit}`);
    const result = await response.json();
    
    if (!result.success) {
      throw new Error(result.message || 'Failed to fetch messages');
    }
    
    return processMessages(result.data.messages, teamMemberIds, blacklistedUserIds);
  }

  const handleDeepSearch = async (query: string) => {
    const walletAddress = walletService.getConnectedWallet();
    if (!walletAddress) throw new Error('Wallet not connected');
    
    const response = await fetch(`/api/messages/search-messages?walletAddress=${walletAddress}&query=${encodeURIComponent(query)}`);
    const result = await response.json();
    
    if (!result.success) {
      throw new Error(result.message || 'Failed to search messages');
    }
    
    return processMessages(result.data, teamMemberIds, blacklistedUserIds);
  }

  const handleSummarize = async (messages: ProcessedMessageLog[]) => {
    const walletAddress = walletService.getConnectedWallet();
    if (!walletAddress) throw new Error('Wallet not connected');
    
    // Format messages for the API
    const formattedMessages = messages.map(msg => ({
      user: msg.user,
      message: msg.message,
      timestamp: msg.timestamp,
      isTeamMember: msg.isTeamMember
    }));
    
    const response = await fetch('/api/messages/summarize', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        walletAddress,
        messages: formattedMessages
      }),
    });
    
    const result = await response.json();
    
    if (!result.success) {
      throw new Error(result.message || 'Failed to summarize messages');
    }
    
    return result.data.summary;
  }

  const handleSendMessage = async (message: string) => {
    const walletAddress = walletService.getConnectedWallet();
    if (!walletAddress) throw new Error('Wallet not connected');
    
    const response = await fetch('/api/messages/send-message', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        walletAddress,
        message
      }),
    });
    
    const result = await response.json();
    
    if (!result.success) {
      throw new Error(result.message || 'Failed to send message');
    }
    
    return result.data;
  }

  return (
    <MessagesClient 
      initialLogs={initialLogs}
      chatId={chatId}
      onLoadMore={handleFetchMore}
      onDeepSearch={handleDeepSearch}
      onSummarize={handleSummarize}
      onSendMessage={handleSendMessage}
      teamMemberIds={teamMemberIds}
      blacklistedUserIds={blacklistedUserIds}
    />
  )
} 