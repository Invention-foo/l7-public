'use client'

import { useEffect, useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Search, FileText, Send } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Spinner } from "@/components/ui/spinner"
import { Badge } from "@/components/ui/badge"
import { createClient } from '@supabase/supabase-js'
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Textarea } from "@/components/ui/textarea"

/* eslint-disable react-hooks/exhaustive-deps */

interface MessageLog {
  user: string
  userId: string
  message: string
  timestamp: string
  id: string
  isTeamMember: boolean
  isBlacklisted: boolean
}

interface MessagesClientProps {
  initialLogs: MessageLog[]
  chatId: string
  onLoadMore: (limit: number) => Promise<MessageLog[]>
  onDeepSearch: (query: string) => Promise<MessageLog[]>
  onSummarize: (messages: MessageLog[]) => Promise<string>
  onSendMessage: (message: string) => Promise<void>
  teamMemberIds: Set<string>
  blacklistedUserIds: Set<string>
}

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

export function MessagesClient({ 
  initialLogs, 
  chatId, 
  onLoadMore, 
  onDeepSearch, 
  onSummarize, 
  onSendMessage,
  teamMemberIds,
}: MessagesClientProps) {
  const [logs, setLogs] = useState<MessageLog[]>(initialLogs)
  const [messageSearch, setMessageSearch] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [messageLimit, setMessageLimit] = useState(100)
  const [isDeepSearchActive, setIsDeepSearchActive] = useState(false)
  const [summarizing, setSummarizing] = useState(false)
  const [summary, setSummary] = useState('')
  const [lastSummarizedAt, setLastSummarizedAt] = useState<Date | null>(null)
  const [cooldownRemaining, setCooldownRemaining] = useState(0)
  const [blacklistedUserIds, setBlacklistedUserIds] = useState<Set<string>>(new Set())
  const [newMessage, setNewMessage] = useState('')
  const [sending, setSending] = useState(false)

  // Function to check if specific user IDs are blacklisted
  const checkBlacklistedUsers = async (userIds: string[]) => {
    if (userIds.length === 0) return new Set<string>()
    
    try {
      console.log('Checking blacklist status for user IDs:', userIds)
      const response = await fetch('/api/messages/check-blacklisted-users', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ userIds })
      })
      const result = await response.json()
      console.log('Blacklist check response:', result)
      
      if (result.success) {
        return new Set(result.data)
      }
      return new Set<string>()
    } catch (error) {
      console.error('Error checking blacklisted users:', error)
      return new Set<string>()
    }
  }

  // Check blacklist status for initial logs
  useEffect(() => {
    const initialUserIds = [...new Set(initialLogs.map(log => log.userId))]
    if (initialUserIds.length > 0) {
      checkBlacklistedUsers(initialUserIds).then(blacklisted => {
        console.log('Initial blacklisted users:', Array.from(blacklisted))
        setBlacklistedUserIds(blacklisted as Set<string>)
        
        // Update initial logs with blacklist status
        setLogs(prevLogs => 
          prevLogs.map(log => ({
            ...log,
            isBlacklisted: blacklisted.has(log.userId)
          }))
        )
      })
    }
  }, []) // Only run once on mount

  useEffect(() => {
    // Check for stored last summarized time
    const storedLastSummarized = localStorage.getItem('lastSummarizedAt')
    if (storedLastSummarized) {
      const lastTime = new Date(storedLastSummarized)
      setLastSummarizedAt(lastTime)
      
      // Calculate remaining cooldown
      const now = new Date()
      const diffMinutes = Math.floor((now.getTime() - lastTime.getTime()) / (1000 * 60))
      const remainingMinutes = Math.max(0, 10 - diffMinutes) // 10 minute cooldown
      setCooldownRemaining(remainingMinutes)
    }
  }, [])

  // Cooldown timer
  useEffect(() => {
    if (cooldownRemaining <= 0) return
    
    const timer = setInterval(() => {
      setCooldownRemaining(prev => {
        const newValue = prev - 1
        return newValue > 0 ? newValue : 0
      })
    }, 60000) // Update every minute
    
    return () => clearInterval(timer)
  }, [cooldownRemaining])

  useEffect(() => {
    console.log('Setting up message subscription for chatId:', chatId)
    console.log('Current blacklisted user IDs:', Array.from(blacklistedUserIds))
    
    // Create a Supabase client for real-time subscriptions only
    const supabase = createClient(
      process.env.NEXT_PUBLIC_SUPABASE_URL || '',
      process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || ''
    )
    
    const channel = supabase
      .channel('message-logs')
      .on(
        'postgres_changes',
        {
          event: 'INSERT',
          schema: 'public',
          table: 'athena_secure_tg_message_logs'
        },
        async (payload) => {
          console.log('New message payload:', payload)
          
          if (!payload.new?.log_id) {
            console.error('Missing log_id in payload')
            return
          }

          // Get the associated log data
          const { data: logData, error } = await supabase
            .from('athena_secure_tg_logs')
            .select('chat_id, user_id, content')
            .eq('id', payload.new.log_id)
            .single()

          console.log('Log data:', logData, 'Error:', error)

          if (error || !logData) {
            console.error('Error fetching log data:', error)
            return
          }

          if (logData.chat_id === chatId) {
            const extractUsername = (content: string): string => {
              // Check if it's a bot-sent message
              if (content.startsWith('Bot sent message:')) {
                return 'NeoGuard'
              }
              
              // Regular user message
              const match = content.match(/Message received in group by (.+)/)
              return match ? match[1] : 'Unknown User'
            }
            
            // Check if this user is blacklisted (check cache first, then API if needed)
            let isUserBlacklisted = blacklistedUserIds.has(logData.user_id)
            
            if (!blacklistedUserIds.has(logData.user_id)) {
              // User not in our current blacklist cache, check API
              const blacklistedCheck = await checkBlacklistedUsers([logData.user_id])
              isUserBlacklisted = blacklistedCheck.has(logData.user_id)
              
              // Update our cache
              if (isUserBlacklisted) {
                setBlacklistedUserIds(prev => new Set([...prev, logData.user_id]))
              }
            }
            
            console.log(`User ${logData.user_id} blacklist status:`, isUserBlacklisted)
            
            const newMessage: MessageLog = {
              user: extractUsername(logData.content),
              userId: logData.user_id,
              message: payload.new.message_text,
              timestamp: payload.new.created_at,
              id: payload.new.id,
              isTeamMember: teamMemberIds.has(logData.user_id),
              isBlacklisted: isUserBlacklisted
            }
            
            console.log('New message created:', newMessage)
            setLogs(prev => [newMessage, ...prev])
          }
        }
      )
      .subscribe((status) => {
        console.log('Subscription status:', status)
      })

    return () => {
      console.log('Cleaning up message subscription')
      supabase.removeChannel(channel)
    }
  }, [chatId, teamMemberIds, blacklistedUserIds])

  const handleLimitChange = async (newLimit: number) => {
    if (isDeepSearchActive) return
    setIsLoading(true)
    setMessageLimit(newLimit)
    try {
      const newLogs = await onLoadMore(newLimit)
      setLogs(newLogs)
    } catch (error) {
      console.error('Error loading more messages:', error)
    }
    setIsLoading(false)
  }

  const handleDeepSearch = async () => {
    if (!messageSearch) return
    setIsLoading(true)
    setIsDeepSearchActive(true)
    try {
      const searchResults = await onDeepSearch(messageSearch)
      setLogs(searchResults)
    } catch (error) {
      console.error('Error performing deep search:', error)
    }
    setIsLoading(false)
  }

  const handleClearSearch = async () => {
    setMessageSearch('')
    setIsDeepSearchActive(false)
    setIsLoading(true)
    try {
      const newLogs = await onLoadMore(messageLimit)
      setLogs(newLogs)
    } catch (error) {
      console.error('Error resetting messages:', error)
    }
    setIsLoading(false)
  }

  const handleSummarize = async () => {
    setSummarizing(true)
    setSummary('')
    
    try {
      // Get the latest 100 messages if not already loaded
      let messagesToSummarize = logs
      if (logs.length < 100 || messageLimit < 100) {
        const newLogs = await onLoadMore(100)
        messagesToSummarize = newLogs
        setLogs(newLogs)
        setMessageLimit(100)
      }
      
      const summaryText = await onSummarize(messagesToSummarize.slice(0, 100))
      setSummary(summaryText)
      
      // Set cooldown
      const now = new Date()
      setLastSummarizedAt(now)
      setCooldownRemaining(10) // 10 minute cooldown
      localStorage.setItem('lastSummarizedAt', now.toISOString())
    } catch (error) {
      console.error('Error summarizing messages:', error)
      setSummary('Failed to generate summary. Please try again later.')
    } finally {
      setSummarizing(false)
    }
  }

  const handleSendMessage = async () => {
    if (!newMessage.trim() || sending) return
    
    setSending(true)
    try {
      await onSendMessage(newMessage.trim())
      setNewMessage('')
      // Optionally show a success toast here
    } catch (error) {
      console.error('Error sending message:', error)
      // Optionally show an error toast here
    } finally {
      setSending(false)
    }
  }

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSendMessage()
    }
  }

  const filteredLogs = logs.filter(log => 
    log.user.toLowerCase().includes(messageSearch.toLowerCase()) ||
    log.userId.includes(messageSearch) ||
    log.message.toLowerCase().includes(messageSearch.toLowerCase())
  )

  return (
    <Card className="bg-gray-900 shadow-lg">
      <CardHeader>
        <div className="flex justify-between items-center">
          <CardTitle className="text-2xl font-bold text-gray-100">Message Logs</CardTitle>
          <div className="flex items-center gap-2">
            <Button
              onClick={handleSummarize}
              disabled={summarizing || cooldownRemaining > 0}
              className="flex items-center gap-2 bg-blue-600 hover:bg-blue-700"
            >
              <FileText className="h-4 w-4" />
              {summarizing ? (
                <>
                  <Spinner className="h-4 w-4 mr-2" />
                  Summarizing...
                </>
              ) : cooldownRemaining > 0 ? (
                `Summarize (${cooldownRemaining}m)`
              ) : (
                'Summarize Last 100 Messages'
              )}
            </Button>
            <Select 
              value={messageLimit.toString()} 
              onValueChange={(value) => handleLimitChange(Number(value))}
              disabled={isDeepSearchActive}
            >
              <SelectTrigger className="w-[180px]">
                <SelectValue placeholder="Select limit" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="100">Last 100 messages</SelectItem>
                <SelectItem value="250">Last 250 messages</SelectItem>
                <SelectItem value="500">Last 500 messages</SelectItem>
                <SelectItem value="1000">Last 1000 messages</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        <div className="mb-4">
          <div className="flex items-center space-x-2">
            <Search className="h-4 w-4 text-gray-400" />
            <Input
              placeholder="Search messages or users..."
              value={messageSearch}
              onChange={(e) => setMessageSearch(e.target.value)}
              className="flex-grow"
            />
            <Button 
              onClick={handleDeepSearch}
              disabled={!messageSearch || isLoading}
            >
              Deep Search
            </Button>
            {isDeepSearchActive && (
              <Button 
                onClick={handleClearSearch}
                disabled={isLoading}
                variant="outline"
              >
                Clear Search
              </Button>
            )}
          </div>
        </div>
        
        {/* Send Message Section */}
        <div className="mb-6 p-4 bg-gray-800 rounded-lg border border-gray-700">
          <h3 className="text-lg font-semibold text-gray-100 mb-3">Send Message to Telegram Group</h3>
          <div className="flex gap-2">
            <Textarea
              placeholder="Type your message here... (Press Enter to send, Shift+Enter for new line)"
              value={newMessage}
              onChange={(e) => setNewMessage(e.target.value)}
              onKeyPress={handleKeyPress}
              className="flex-grow min-h-[80px] bg-gray-700 border-gray-600 text-gray-100 placeholder-gray-400"
              disabled={sending}
            />
            <Button
              onClick={handleSendMessage}
              disabled={!newMessage.trim() || sending}
              className="self-end bg-green-600 hover:bg-green-700"
            >
              {sending ? (
                <>
                  <Spinner className="h-4 w-4 mr-2" />
                  Sending...
                </>
              ) : (
                <>
                  <Send className="h-4 w-4 mr-2" />
                  Send
                </>
              )}
            </Button>
          </div>
        </div>
        
        {summary && (
          <Alert className="mb-4 bg-blue-900 border-blue-700 text-white">
            <FileText className="h-4 w-4" />
            <AlertTitle className="flex items-center gap-2">
              Message Summary
              <Badge variant="outline" className="border-blue-400 text-blue-200">
                Last 100 messages
              </Badge>
            </AlertTitle>
            <AlertDescription className="mt-2 whitespace-pre-line">
              {summary}
            </AlertDescription>
            <div className="mt-3 text-xs text-blue-300">
              {lastSummarizedAt && (
                <>Generated at {lastSummarizedAt.toLocaleTimeString()} • </>
              )}
              Next summary available in {cooldownRemaining > 0 ? cooldownRemaining : 0} minutes
            </div>
          </Alert>
        )}
        
        {isLoading ? (
          <div className="flex justify-center py-4">
            <Spinner />
          </div>
        ) : (
          <ScrollArea className="h-[600px] w-full rounded-md">
            {filteredLogs.map((log, i) => (
              <div key={i} className="mb-4 p-3 bg-gray-800 rounded-md hover:bg-gray-750 transition-colors duration-200">
                <div className="flex items-center gap-2">
                  <span className="font-bold text-gray-100">{log.user}</span>
                  {log.isTeamMember && (
                    <Badge variant="secondary" className="bg-blue-600 text-white">
                      Team
                    </Badge>
                  )}
                  {log.isBlacklisted && (
                    <Badge variant="destructive" className="bg-red-600 text-white">
                      Blacklisted
                    </Badge>
                  )}
                </div>
                <p className="text-sm text-gray-200">
                  (ID: {log.userId}): {log.message}
                </p>
                <div className="text-sm text-gray-400">
                  {formatTimestamp(log.timestamp)}
                </div>
              </div>
            ))}
          </ScrollArea>
        )}
      </CardContent>
    </Card>
  )
} 