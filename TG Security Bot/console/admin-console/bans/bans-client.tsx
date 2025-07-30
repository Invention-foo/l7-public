'use client'

import { useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Badge } from "@/components/ui/badge"
import { Search } from "lucide-react"
import { Button } from "@/components/ui/button"
import { toast } from "react-hot-toast"
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "@/components/ui/select"
import { walletService } from '@/services/wallet.service'

interface BanLog {
  user: string
  userId: string
  reason: string
  chat: string
  timestamp: string
  globalBan: boolean
  spamMessage?: string
  reviewed: boolean
}

type FilterType = 'all' | 'spam' | 'impersonation' | 'impersonation-mm' | 'global'

function formatTimestamp(timestamp: string) {
  const date = new Date(timestamp)
  return date.toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: true,
    timeZone: 'UTC'
  }) + ' UTC'
}

async function submitReview(userId: string, messageText: string) {
  try {
    const walletAddress = walletService.getConnectedWallet();
    if (!walletAddress) {
      throw new Error('Wallet not connected');
    }
    
    const response = await fetch('/api/bans/submit-review', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        userId,
        messageText,
        walletAddress
      }),
    });
    
    const result = await response.json();
    
    if (!result.success) {
      throw new Error(result.message || 'Failed to submit review');
    }
    
    return true;
  } catch (error) {
    console.error('Error submitting review:', error);
    return false;
  }
}

export function BansClient({ initialLogs }: { initialLogs: BanLog[] }) {
  const [banSearch, setBanSearch] = useState('')
  const [filter, setFilter] = useState<FilterType>('all')
  const [reviewedLogs, setReviewedLogs] = useState(
    new Set(initialLogs.filter(log => log.reviewed).map(log => log.userId))
  )

  const filteredBanLogs = initialLogs.filter(log => {
    const matchesSearch = 
      log.user.toLowerCase().includes(banSearch.toLowerCase()) ||
      log.userId.includes(banSearch) ||
      log.reason.toLowerCase().includes(banSearch.toLowerCase()) ||
      log.chat.toLowerCase().includes(banSearch.toLowerCase())

    switch (filter) {
      case 'spam':
        return matchesSearch && log.reason === 'spam'
      case 'impersonation':
        return matchesSearch && log.reason === 'impersonation'
      case 'impersonation-mm':
        return matchesSearch && log.reason === 'impersonation-mm'
      case 'global':
        return matchesSearch && log.globalBan
      default:
        return matchesSearch
    }
  })

  const handleReviewSubmit = async (userId: string, messageText: string) => {
    const success = await submitReview(userId, messageText)
    if (success) {
      setReviewedLogs(prev => new Set([...prev, userId]))
      toast.success('Ban has been flagged for review')
    } else {
      toast.error('Failed to submit review')
    }
  }

  return (
    <Card className="bg-gray-900 shadow-lg">
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle className="text-2xl font-bold text-gray-100">Ban Logs</CardTitle>
        <Select value={filter} onValueChange={(value: FilterType) => setFilter(value)}>
          <SelectTrigger className="w-40 bg-gray-800 text-gray-100 border-gray-700">
            <SelectValue placeholder="Filter by" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Bans</SelectItem>
            <SelectItem value="spam">Spam</SelectItem>
            <SelectItem value="impersonation">Impersonation</SelectItem>
            <SelectItem value="impersonation-mm">MM Impersonation</SelectItem>
            <SelectItem value="global">Global Bans</SelectItem>
          </SelectContent>
        </Select>
      </CardHeader>
      <CardContent>
        <div className="mb-4 flex items-center">
          <Search className="mr-2 h-4 w-4 text-gray-400" />
          <Input
            placeholder="Search banned users..."
            value={banSearch}
            onChange={(e) => setBanSearch(e.target.value)}
            className="flex-grow bg-gray-800 text-gray-100 border-gray-700 focus:border-[#b829e3]"
          />
        </div>
        <ScrollArea className="h-[600px] w-full rounded-md">
          {filteredBanLogs.map((log) => (
            <div 
              key={`${log.userId}-${log.timestamp}`} 
              className="mb-4 p-4 bg-gray-800 rounded-md hover:bg-gray-750 transition-colors duration-200"
            >
              <div className="flex justify-between items-start">
                <p className="text-sm text-gray-200">
                  <span className="font-bold text-gray-100">{log.user}</span> (ID: {log.userId}) was banned for {log.reason}.
                </p>
                {log.reason === 'spam' && log.spamMessage && (
                  <Button
                    variant="outline"
                    size="sm"
                    className={`text-xs ${
                      log.reviewed || reviewedLogs.has(log.userId)
                        ? 'bg-gray-600 cursor-not-allowed'
                        : 'bg-blue-600 hover:bg-blue-700'
                    } text-white border-0 ml-2`}
                    onClick={() => handleReviewSubmit(log.userId, log.spamMessage!)}
                    disabled={log.reviewed || reviewedLogs.has(log.userId)}
                  >
                    {log.reviewed || reviewedLogs.has(log.userId) ? 'Flagged for Review' : 'Flag for Review'}
                  </Button>
                )}
              </div>
              {log.reason === 'spam' && log.spamMessage && (
                <p className="mt-2 text-sm text-gray-400 italic">
                  Spam message: &quot;{log.spamMessage}&quot;
                </p>
              )}
              <div className="flex justify-between items-center mt-2">
                <p className="text-xs text-gray-400">Timestamp: {formatTimestamp(log.timestamp)}</p>
                <div className="flex items-center space-x-2">
                  <Badge variant="secondary" className="bg-blue-600 text-gray-100">
                    {log.reason}
                  </Badge>
                  {log.globalBan && (
                    <Badge variant="secondary" className="bg-red-600 text-gray-100">
                      global ban
                    </Badge>
                  )}
                </div>
              </div>
            </div>
          ))}
        </ScrollArea>
      </CardContent>
    </Card>
  )
}