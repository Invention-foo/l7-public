/* eslint-disable @typescript-eslint/no-unused-vars */
/* eslint-disable @typescript-eslint/no-explicit-any */
'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { walletService } from '@/services/wallet.service';
import { useDisconnect } from '@reown/appkit/react';
import { Copy, Check } from 'lucide-react';
import { DashboardClient } from './dashboard/dashboard-client';

export default function AdminConsolePage() {
  const [loading, setLoading] = useState(true);
  const [userData, setUserData] = useState<any>(null);
  const [error, setError] = useState('');
  const [isExpanded, setIsExpanded] = useState(false);
  const router = useRouter();
  const { disconnect } = useDisconnect();
  const [copied, setCopied] = useState(false);
  const [dashboardData, setDashboardData] = useState<any>(null);
  const [dashboardLoading, setDashboardLoading] = useState(false);
  
  useEffect(() => {
    async function checkWalletAndEligibility() {
      try {
        // Check if wallet is connected
        const connectedWallet = walletService.getConnectedWallet();
        
        if (!connectedWallet) {
          // No wallet connected, redirect to login
          router.push('/login');
          return;
        }
        
        // Fetch user data
        const response = await fetch(`/api/users/get-user?walletAddress=${connectedWallet}`);
        const result = await response.json();
        
        if (!result.success) {
          throw new Error(result.message || 'Failed to fetch user data');
        }
        
        setUserData(result.user);
        // Set expanded state based on whether telegram_chat_id exists
        setIsExpanded(!result.user.telegram_chat_id);
        
        // If user has telegram_chat_id, fetch dashboard data
        if (result.user.telegram_chat_id) {
          await fetchDashboardData(result.user.telegram_chat_id);
        }
      } catch (err) {
        console.error('Error checking wallet:', err);
        setError('Failed to authenticate. Please try again.');
      } finally {
        setLoading(false);
      }
    }
    
    checkWalletAndEligibility();
  }, [router]);
  
  const fetchDashboardData = async (chatId: string) => {
    setDashboardLoading(true);
    try {
      const response = await fetch(`/api/dashboard/get-stats?chatId=${chatId}`);
      const result = await response.json();
      
      if (!result.success) {
        throw new Error(result.message || 'Failed to fetch dashboard data');
      }
      
      setDashboardData(result.data);
    } catch (err) {
      console.error('Error fetching dashboard data:', err);
      // We don't set the main error state here to avoid blocking the whole page
    } finally {
      setDashboardLoading(false);
    }
  };
  
  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };
  
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
          onClick={() => router.push('/login')}
          className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700"
        >
          Back to Login
        </button>
      </div>
    );
  }
  
  return (
    <div className="container mx-auto px-4 py-8">
      <div className="mb-6">
        <h1 className="text-3xl font-bold">Admin Console</h1>
      </div>
      
      {userData && (
        <>
          <div className="bg-gray-900 shadow-md rounded-lg p-6 border border-gray-800 mb-8">
            {!isExpanded && userData.telegram_chat_id ? (
              <div className="flex items-center justify-between">
                <h2 className="text-xl font-semibold text-blue-500">User Information</h2>
                <div className="flex items-center gap-4">
                  <div className="flex items-center">
                    <span className="text-gray-500 mr-1">Wallet:</span> 
                    <span className="font-mono text-xs bg-gray-800 px-2 py-1 rounded">
                      {userData.wallet_address.substring(0, 8)}...{userData.wallet_address.substring(userData.wallet_address.length - 6)}
                    </span>
                    <button 
                      onClick={() => copyToClipboard(userData.wallet_address)}
                      className="ml-1 p-1 text-gray-400 hover:text-blue-400 rounded-full hover:bg-gray-800"
                      title="Copy wallet address"
                    >
                      {copied ? <Check size={14} /> : <Copy size={14} />}
                    </button>
                  </div>
                  <div className="flex items-center">
                    <span className="text-gray-500 mr-1">Telegram:</span> 
                    <span className="font-mono text-xs bg-gray-800 px-2 py-1 rounded">{userData.telegram_chat_id}</span> 
                    <span className="ml-1 text-green-500">✅</span>
                  </div>
                  <button
                    onClick={() => setIsExpanded(!isExpanded)}
                    className="px-3 py-1 bg-gray-700 text-gray-300 rounded-md hover:bg-gray-600 text-sm"
                  >
                    Expand
                  </button>
                </div>
              </div>
            ) : (
              <>
                <div className="flex justify-between items-center mb-4">
                  <h2 className="text-xl font-semibold text-blue-500">User Information</h2>
                  {userData.telegram_chat_id && (
                    <button
                      onClick={() => setIsExpanded(!isExpanded)}
                      className="px-3 py-1 bg-gray-700 text-gray-300 rounded-md hover:bg-gray-600 text-sm"
                    >
                      Collapse
                    </button>
                  )}
                </div>
                
                <div className="mb-6">
                  <div className="flex justify-between items-center mb-2">
                    <h2 className="text-xl font-semibold text-blue-500">Your Wallet</h2>
                    <button 
                      onClick={() => copyToClipboard(userData.wallet_address)}
                      className="p-1 text-gray-400 hover:text-blue-400 rounded-full hover:bg-gray-800 flex items-center gap-1"
                      title="Copy wallet address"
                    >
                      {copied ? (
                        <>
                          <Check size={16} />
                          <span className="text-xs">Copied!</span>
                        </>
                      ) : (
                        <>
                          <Copy size={16} />
                          <span className="text-xs">Copy</span>
                        </>
                      )}
                    </button>
                  </div>
                  <p className="font-mono bg-gray-800 p-2 rounded border border-gray-700 text-white">{userData.wallet_address}</p>
                </div>
                
                <TelegramIntegration 
                  userData={userData} 
                  onUpdate={() => {
                    // Refresh dashboard data when Telegram ID is updated
                    if (userData.telegram_chat_id) {
                      fetchDashboardData(userData.telegram_chat_id);
                    }
                  }}
                />
              </>
            )}
          </div>
          
          {userData.telegram_chat_id && (
            <div className="bg-gray-900 shadow-md rounded-lg p-6 border border-gray-800">
              <h2 className="text-xl font-semibold mb-4 text-blue-500">Analytics Dashboard</h2>
              {dashboardLoading ? (
                <div className="flex justify-center items-center py-12">
                  <div className="animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-blue-500"></div>
                </div>
              ) : dashboardData ? (
                <DashboardClient data={dashboardData} />
              ) : (
                <div className="text-center py-8 text-gray-400">
                  No dashboard data available
                </div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}

function TelegramIntegration({ userData, onUpdate }: { userData: any, onUpdate: () => void }) {
  const [chatId, setChatId] = useState(userData.telegram_chat_id || '');
  const [isSaving, setIsSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState('');
  const [showModal, setShowModal] = useState(!userData.telegram_chat_id);
  const [isEditing, setIsEditing] = useState(false);
  const router = useRouter();
  
  const saveTelegramChatId = async (chatId: string) => {
    setIsSaving(true);
    setSaveMessage('');
    
    try {
      // Get the connected wallet address
      const walletAddress = userData.wallet_address;
      
      // Create a message to sign
      const timestamp = Date.now();
      const message = `Update Telegram Chat ID to ${chatId} for wallet ${walletAddress} at timestamp ${timestamp}`;
      
      // Request signature from wallet
      // This assumes you have access to the signing method - you may need to adjust based on your wallet integration
      const signature = await (window.ethereum as any).request({
        method: 'personal_sign',
        params: [message, walletAddress]
      });
      
      // Send the request with signature
      const response = await fetch('/api/users/update-telegram', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          walletAddress,
          telegramChatId: chatId,
          signature,
          message,
          timestamp
        })
      });
      
      const result = await response.json();
      
      if (!result.success) {
        // Check if this is a uniqueness conflict error
        if (response.status === 409) {
          setSaveMessage(`Error: ${result.message}`);
          setIsEditing(false); // Reset editing state
          return;
        }
        throw new Error(result.message || 'Failed to update Telegram chat ID');
      }
      
      setSaveMessage('Telegram chat ID saved successfully!');
      setShowModal(false);
      
      // Call the onUpdate callback to refresh dashboard data
      onUpdate();
      
      // Refresh the page to update the UI
      window.location.reload();
    } catch (error) {
      console.error('Error saving telegram chat ID:', error);
      setSaveMessage(`Error saving telegram chat ID: ${(error as Error).message || 'Please try again'}`);
    } finally {
      setIsSaving(false);
    }
  };
  
  return (
    <>
      <div className={`mb-6 ${userData.telegram_chat_id ? 'bg-gray-800' : 'bg-gray-800 border-2 border-blue-500'} p-4 rounded-lg`}>
        <div className="flex justify-between items-center mb-2">
          <h2 className="text-xl font-semibold text-blue-500">Telegram Integration</h2>
          {userData.telegram_chat_id && (
            <button
              onClick={() => setIsEditing(!isEditing)}
              className="px-3 py-1 bg-gray-700 text-gray-300 rounded-md hover:bg-gray-600 text-sm"
            >
              {isEditing ? 'Cancel' : 'Edit'}
            </button>
          )}
        </div>
        
        {userData.telegram_chat_id ? (
          <>
            <p className="text-gray-300 mb-4">
              {isEditing 
                ? "Warning: Changing your Telegram Chat ID will affect the bot's ability to moderate your existing chat."
                : "Your Telegram chat is connected and ready to be moderated by NeoGuard."}
            </p>
            <div className="flex items-center gap-2">
              <input
                type="text"
                value={chatId}
                onChange={(e) => setChatId(e.target.value)}
                disabled={!isEditing}
                className={`w-full p-2 rounded bg-gray-700 text-white border ${isEditing ? 'border-blue-500' : 'border-gray-700'}`}
              />
              {isEditing && (
                <button
                  onClick={() => saveTelegramChatId(chatId)}
                  disabled={isSaving}
                  className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:opacity-50"
                >
                  {isSaving ? 'Saving...' : 'Save'}
                </button>
              )}
            </div>
            
            {/* Next steps instructions */}
            <div className="mt-4 bg-blue-900/30 p-4 rounded-lg border border-blue-600/50">
              <h4 className="text-blue-400 font-semibold mb-2">After saving your Chat ID:</h4>
              <ol className="text-gray-300 text-sm space-y-1 list-decimal list-inside">
                <li>Invite <span className="font-mono bg-gray-800 px-1 rounded">@neoguardAI_bot</span> to your Telegram group</li>
                <li>Give the bot admin permissions in your group</li>
                <li>Run <span className="font-mono bg-gray-800 px-1 rounded">/autosetup</span> in your group to configure the admin list</li>
              </ol>
            </div>
          </>
        ) : (
          <>
            <p className="text-gray-300 mb-4">
              <strong className="text-red-400">Required:</strong> Please set your Telegram Chat ID to enable NeoGuard protection.
              All dashboard features will be available after connecting your Telegram chat.
            </p>
            
            {/* Instructions for getting Chat ID */}
            <div className="bg-gray-700 p-4 rounded-lg mb-4 border-l-4 border-blue-500">
              <h3 className="text-blue-400 font-semibold mb-2">How to get your Telegram Chat ID:</h3>
              <ol className="text-gray-300 text-sm space-y-1 list-decimal list-inside">
                <li>Add <span className="font-mono bg-gray-800 px-1 rounded">@getidsbot</span> to your Telegram group</li>
                <li>The bot will reply with your group&apos;s Chat ID (it will be a negative number)</li>
                <li>Copy the Chat ID and paste it below</li>
                <li>Remove the bot from your group after getting the ID</li>
              </ol>
              <p className="text-yellow-400 text-xs mt-2">
                ⚠️ Make sure to use the group Chat ID (negative number), not a user ID
              </p>
            </div>
            
            <div className="flex items-center gap-2 mb-4">
              <input
                type="text"
                value={chatId}
                onChange={(e) => setChatId(e.target.value)}
                placeholder="Enter your Telegram Chat ID (e.g., -1001234567890)"
                className="w-full p-2 rounded bg-gray-700 text-white border border-blue-500"
              />
            </div>
            
            {/* Next steps instructions */}
            <div className="mb-4 bg-blue-900/30 p-4 rounded-lg border border-blue-600/50">
              <h4 className="text-blue-400 font-semibold mb-2">After saving your Chat ID:</h4>
              <ol className="text-gray-300 text-sm space-y-1 list-decimal list-inside">
                <li>Invite <span className="font-mono bg-gray-700 px-1 rounded">@neoguardAI_bot</span> to your Telegram group</li>
                <li>Give the bot admin permissions in your group</li>
                <li>Run <span className="font-mono bg-gray-700 px-1 rounded">/autosetup</span> in your group to configure the admin list</li>
              </ol>
            </div>
            
            <div className="flex justify-end">
              <button
                onClick={() => saveTelegramChatId(chatId)}
                disabled={isSaving}
                className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:opacity-50"
              >
                {isSaving ? 'Saving...' : 'Save'}
              </button>
            </div>
          </>
        )}
        
        {saveMessage && (
          <div className={`mt-2 p-2 rounded ${saveMessage.includes('Error') ? 'bg-red-900 text-red-100' : 'bg-green-900 text-green-100'}`}>
            <p className="text-sm">
              {saveMessage}
              {saveMessage.includes('contact @invention20') && (
                <span className="block mt-1 font-bold">
                  Please contact @invention20 on Telegram for assistance.
                </span>
              )}
            </p>
          </div>
        )}
      </div>
      
      {/* Modal for setting up Telegram chat ID */}
      {showModal && (
        <div className="fixed inset-0 bg-black bg-opacity-70 flex items-center justify-center z-50">
          <div className="bg-gray-900 p-6 rounded-lg shadow-lg max-w-lg w-full border border-gray-800">
            <h2 className="text-xl font-bold text-blue-500 mb-4">Welcome to NeoGuard!</h2>
            <p className="text-gray-300 mb-4">
              To get started with NeoGuard protection, you need to connect your Telegram chat.
            </p>
            
            {/* Instructions for getting Chat ID */}
            <div className="bg-gray-800 p-4 rounded-lg mb-4 border border-blue-600">
              <h3 className="text-blue-400 font-semibold mb-2">How to get your Telegram Chat ID:</h3>
              <ol className="text-gray-300 text-sm space-y-1 list-decimal list-inside">
                <li>Add <span className="font-mono bg-gray-700 px-1 rounded">@getidsbot</span> to your Telegram group</li>
                <li>The bot will reply with your group&apos;s Chat ID (negative number)</li>
                <li>Copy the Chat ID and paste it below</li>
                <li>Remove the bot from your group after getting the ID</li>
              </ol>
              <p className="text-yellow-400 text-xs mt-2">
                ⚠️ Use the group Chat ID (negative number), not a user ID
              </p>
            </div>
            
            <div className="flex items-center gap-2 mb-4">
              <input
                type="text"
                value={chatId}
                onChange={(e) => setChatId(e.target.value)}
                placeholder="Enter your Telegram Chat ID (e.g., -1001234567890)"
                className="w-full p-2 rounded bg-gray-700 text-white border border-blue-500"
              />
            </div>
            
            {/* Next steps instructions */}
            <div className="mb-4 bg-blue-900/30 p-4 rounded-lg border border-blue-600/50">
              <h4 className="text-blue-400 font-semibold mb-2">After saving your Chat ID:</h4>
              <ol className="text-gray-300 text-sm space-y-1 list-decimal list-inside">
                <li>Invite <span className="font-mono bg-gray-700 px-1 rounded">@neoguardAI_bot</span> to your Telegram group</li>
                <li>Give the bot admin permissions in your group</li>
                <li>Run <span className="font-mono bg-gray-700 px-1 rounded">/autosetup</span> in your group to configure the admin list</li>
              </ol>
            </div>
            
            <div className="flex justify-end">
              <button
                onClick={() => saveTelegramChatId(chatId)}
                disabled={isSaving}
                className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:opacity-50"
              >
                {isSaving ? 'Saving...' : 'Save'}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
