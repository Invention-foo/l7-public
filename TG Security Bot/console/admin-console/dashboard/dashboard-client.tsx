/* eslint-disable @typescript-eslint/no-explicit-any */
'use client'

import { useEffect, useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Line, Bar } from 'react-chartjs-2'
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  BarElement,
  Title,
  Tooltip,
  Legend
} from 'chart.js'
import { fetchTimeSeriesData } from './actions'

// Register ChartJS components
ChartJS.register(
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  BarElement,
  Title,
  Tooltip,
  Legend
)

interface DashboardData {
  userChat: {
    usersBanned: number
    messagesScanned: number
    spamMessagesDeleted: number
  }
  partnerNetwork: {
    totalUsersBanned: number
    totalMessagesScanned: number
    totalSpamDeleted: number
    globalBlacklistedUsers: number
  }
  banRateOverTime: number[]
  messageRateOverTime: number[]
  chatId: string
}

type TimeFrame = 'daily' | 'weekly' | 'monthly'

function MetricChart({ data, timeFrame, color, type = 'line' }: { 
  data: number[], 
  timeFrame: TimeFrame,
  color: string,
  type?: 'line' | 'bar'
}) {
  const now = new Date()
  now.setUTCHours(0, 0, 0, 0)
  
  const labels = data.map((_, i) => {
    const date = new Date(now)
    if (timeFrame === 'daily') {
      date.setUTCDate(date.getUTCDate() - (6 - i))
      return date.toLocaleDateString('en-US', { 
        month: 'short', 
        day: 'numeric',
        timeZone: 'UTC'
      }) + ' UTC'
    } else if (timeFrame === 'weekly') {
      date.setUTCDate(date.getUTCDate() - (6 - i) * 7)
      return date.toLocaleDateString('en-US', { 
        month: 'short', 
        day: 'numeric',
        timeZone: 'UTC'
      }) + ' UTC'
    } else {
      date.setUTCMonth(date.getUTCMonth() - (6 - i))
      return date.toLocaleDateString('en-US', { 
        month: 'short', 
        year: 'numeric',
        timeZone: 'UTC'
      }) + ' UTC'
    }
  })

  // Create gradient for line chart
  const getGradient = (ctx: any, chartArea: any) => {
    if (!chartArea) return null;
    const gradient = ctx.createLinearGradient(0, chartArea.bottom, 0, chartArea.top);
    
    if (type === 'line') {
      // More pronounced gradient for line charts
      gradient.addColorStop(0, 'rgba(96, 165, 250, 0.0)');   // Transparent at bottom
      gradient.addColorStop(0.2, 'rgba(96, 165, 250, 0.1)'); // Very light blue
      gradient.addColorStop(0.8, 'rgba(96, 165, 250, 0.25)'); // Medium blue
      gradient.addColorStop(1, 'rgba(96, 165, 250, 0.35)');  // Stronger blue at top
    } else {
      // Gradient for bar charts
      gradient.addColorStop(0, 'rgba(59, 130, 246, 0.6)');   // Medium blue at bottom
      gradient.addColorStop(1, 'rgba(37, 99, 235, 0.9)');    // Darker blue at top
    }
    
    return gradient;
  };

  // Get bar gradient
  const getBarGradient = (ctx: any, chartArea: any) => {
    if (!chartArea) return color;
    const gradient = ctx.createLinearGradient(0, chartArea.bottom, 0, chartArea.top);
    gradient.addColorStop(0, 'rgba(59, 130, 246, 0.7)');  // Medium blue
    gradient.addColorStop(1, 'rgba(37, 99, 235, 0.9)');   // Darker blue
    return gradient;
  };

  const chartData = {
    labels,
    datasets: [
      {
        label: '',
        data: data,
        borderColor: type === 'line' ? 'rgba(96, 165, 250, 1)' : undefined,
        backgroundColor: (context: any) => {
          const chart = context.chart;
          const {ctx, chartArea} = chart;
          
          if (type === 'line') {
            return chartArea ? getGradient(ctx, chartArea) : 'rgba(59, 130, 246, 0.2)';
          } else {
            return chartArea ? getBarGradient(ctx, chartArea) : color;
          }
        },
        borderWidth: type === 'line' ? 3 : 0,
        tension: type === 'line' ? 0.4 : undefined,
        pointRadius: type === 'line' ? 0 : undefined,
        pointBackgroundColor: type === 'line' ? '#ffffff' : undefined,
        pointBorderColor: type === 'line' ? 'rgba(59, 130, 246, 1)' : undefined,
        pointBorderWidth: type === 'line' ? 2 : undefined,
        pointHoverRadius: type === 'line' ? 6 : undefined,
        pointHoverBackgroundColor: type === 'line' ? '#ffffff' : undefined,
        pointHoverBorderColor: type === 'line' ? 'rgba(37, 99, 235, 1)' : undefined,
        pointHoverBorderWidth: type === 'line' ? 3 : undefined,
        fill: type === 'line' ? true : undefined,
        barPercentage: type === 'bar' ? 0.5 : undefined,
        categoryPercentage: type === 'bar' ? 0.7 : undefined,
        borderRadius: type === 'bar' ? 6 : undefined,
      },
    ],
  }

  const options = {
    responsive: true,
    maintainAspectRatio: false,
    animation: {
      duration: 1500,
      easing: 'easeOutQuart' as const
    },
    plugins: {
      legend: {
        display: false,
      },
      tooltip: {
        backgroundColor: 'rgba(15, 23, 42, 0.9)',
        titleColor: '#94a3b8',
        bodyColor: '#f8fafc',
        padding: 16,
        borderColor: '#1e293b',
        borderWidth: 1,
        cornerRadius: 8,
        displayColors: false,
        boxShadow: '0 10px 15px -3px rgba(0, 0, 0, 0.1)',
        callbacks: {
          title: (items: any) => {
            return items[0].label + ' UTC';
          },
          label: (context: any) => {
            return `Value: ${context.parsed.y}`;
          }
        },
        titleFont: {
          size: 14,
          weight: 'normal' as const,
          family: "'Inter', sans-serif"
        },
        bodyFont: {
          size: 16,
          weight: 'bold' as const,
          family: "'Inter', sans-serif"
        }
      }
    },
    scales: {
      y: {
        beginAtZero: true,
        grid: {
          color: 'rgba(51, 65, 85, 0.2)',
          drawBorder: false,
          drawTicks: false,
          lineWidth: 1
        },
        ticks: {
          color: '#94a3b8',
          padding: 12,
          font: {
            size: 12,
            family: "'Inter', sans-serif"
          },
          maxTicksLimit: 5
        },
        border: {
          display: false
        }
      },
      x: {
        grid: {
          display: false,
        },
        ticks: {
          color: '#94a3b8',
          padding: 12,
          font: {
            size: 12,
            family: "'Inter', sans-serif"
          }
        },
        border: {
          display: false
        }
      },
    },
    elements: {
      line: {
        borderJoinStyle: 'round' as const,
        borderCapStyle: 'round' as const,
        cubicInterpolationMode: 'monotone' as const
      },
      point: {
        hitRadius: 10,
        hoverBorderWidth: 3
      }
    },
    layout: {
      padding: {
        top: 24,
        right: 24,
        bottom: 16,
        left: 16
      }
    },
    interaction: {
      mode: 'index' as const,
      intersect: false
    }
  }

  return (
    <div className="h-[280px] relative">
      {type === 'line' ? (
        <Line data={chartData} options={options} />
      ) : (
        <Bar data={chartData} options={options} />
      )}
    </div>
  )
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const processTimeSeriesData = (queryResult: any, timeFrame: TimeFrame) => {
  const periods = 7
  const buckets = new Array(periods).fill(0)
  
  if (!queryResult || !Array.isArray(queryResult)) return buckets
  
  // Create a map of period start times to counts
  const periodMap = new Map(
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    queryResult.map((record: any) => {
      const date = new Date(record.period_start)
      // Normalize to start of period
      if (timeFrame === 'daily') {
        date.setUTCHours(0, 0, 0, 0)
      } else if (timeFrame === 'weekly') {
        date.setUTCHours(0, 0, 0, 0)
        // PostgreSQL weeks start on Monday, so align to Monday
        const day = date.getUTCDay()
        const diff = day === 0 ? 6 : day - 1 // Adjust Sunday to be 6 days back
        date.setUTCDate(date.getUTCDate() - diff)
      } else { // monthly
        date.setUTCDate(1)
        date.setUTCHours(0, 0, 0, 0)
      }
      return [date.getTime(), parseInt(record.count)]
    })
  )
  
  // Generate the expected period start times
  const now = new Date()
  now.setUTCHours(0, 0, 0, 0)
  
  const periodStarts = Array.from({ length: periods }, (_, i) => {
    const date = new Date(now)
    if (timeFrame === 'daily') {
      date.setUTCDate(date.getUTCDate() - (periods - 1 - i))
    } else if (timeFrame === 'weekly') {
      // Align to current week's Monday first
      const day = date.getUTCDay()
      const diff = day === 0 ? 6 : day - 1
      date.setUTCDate(date.getUTCDate() - diff)
      // Then go back by weeks
      date.setUTCDate(date.getUTCDate() - (periods - 1 - i) * 7)
    } else { // monthly
      date.setUTCDate(1)
      date.setUTCMonth(date.getUTCMonth() - (periods - 1 - i))
    }
    return date.getTime()
  })
  
  // Fill the buckets with counts, using 0 for missing periods
  periodStarts.forEach((startTime, i) => {
    buckets[i] = periodMap.get(startTime) || 0
  })
  
  return buckets
}

export function DashboardClient({ data: initialData }: { data: DashboardData }) {
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const [data, setData] = useState(initialData)
  const [banTimeFrame, setBanTimeFrame] = useState<TimeFrame>('daily')
  const [messageTimeFrame, setMessageTimeFrame] = useState<TimeFrame>('daily')
  const [timeSeriesData, setTimeSeriesData] = useState({
    banRateOverTime: processTimeSeriesData(initialData.banRateOverTime, 'daily'),
    messageRateOverTime: processTimeSeriesData(initialData.messageRateOverTime, 'daily')
  })

  useEffect(() => {
    const updateTimeSeriesData = async () => {
      const { banRateData, messageRateData } = await fetchTimeSeriesData(
        data.chatId,
        banTimeFrame,
        messageTimeFrame
      )
      
      setTimeSeriesData({
        banRateOverTime: processTimeSeriesData(banRateData, banTimeFrame),
        messageRateOverTime: processTimeSeriesData(messageRateData, messageTimeFrame)
      })
    }
    
    updateTimeSeriesData()
  }, [banTimeFrame, messageTimeFrame, data.chatId])

  return (
    <div className="space-y-6">
      <Card className="bg-gray-900 shadow-lg">
        <CardContent className="pt-6">
          <div className="flex justify-between items-center mb-4">
            <CardTitle className="text-xl font-bold text-gray-100">Neoguard Network</CardTitle>
          </div>
          <div className="grid grid-cols-4 gap-4">
            <div className="text-center">
              <p className="text-sm font-medium text-gray-400">Total Users Banned</p>
              <p className="text-2xl font-bold text-gray-100">{data.partnerNetwork.totalUsersBanned}</p>
            </div>
            <div className="text-center">
              <p className="text-sm font-medium text-gray-400">Total Messages Scanned</p>
              <p className="text-2xl font-bold text-gray-100">{data.partnerNetwork.totalMessagesScanned}</p>
            </div>
            <div className="text-center">
              <p className="text-sm font-medium text-gray-400">Total Spam Messages Deleted</p>
              <p className="text-2xl font-bold text-gray-100">{data.partnerNetwork.totalSpamDeleted}</p>
            </div>
            <div className="text-center">
              <p className="text-sm font-medium text-gray-400">Global Blacklisted Users</p>
              <p className="text-2xl font-bold text-gray-100">{data.partnerNetwork.globalBlacklistedUsers}</p>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card className="bg-gray-900 shadow-lg">
        <CardHeader>
          <CardTitle className="text-2xl font-bold text-gray-100">Your Community Statistics</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-3 gap-4 mb-6">
            <Card className="bg-gray-800 p-4">
              <CardTitle className="text-lg text-gray-300 text-center">Users Banned</CardTitle>
              <p className="text-3xl font-bold text-gray-100 mt-2 text-center">{data.userChat.usersBanned}</p>
            </Card>
            <Card className="bg-gray-800 p-4">
              <CardTitle className="text-lg text-gray-300 text-center">Messages Scanned</CardTitle>
              <p className="text-3xl font-bold text-gray-100 mt-2 text-center">{data.userChat.messagesScanned}</p>
            </Card>
            <Card className="bg-gray-800 p-4">
              <CardTitle className="text-lg text-gray-300 text-center">Spam Messages Deleted</CardTitle>
              <p className="text-3xl font-bold text-gray-100 mt-2 text-center">{data.userChat.spamMessagesDeleted}</p>
            </Card>
          </div>
          
          <div className="grid grid-cols-2 gap-4">
            <Card className="bg-gray-800 p-4">
              <div className="flex justify-between items-center mb-4">
                <CardTitle className="text-lg text-gray-300">Ban Rate Over Time</CardTitle>
                <Select value={banTimeFrame} onValueChange={(value: TimeFrame) => setBanTimeFrame(value)}>
                  <SelectTrigger className="w-32 bg-gray-800 border-gray-700 text-gray-100">
                    <SelectValue placeholder="Select timeframe" />
                  </SelectTrigger>
                  <SelectContent className="bg-gray-800 border-gray-700 text-gray-100">
                    <SelectItem value="daily" className="text-gray-100 hover:bg-gray-700">Daily</SelectItem>
                    <SelectItem value="weekly" className="text-gray-100 hover:bg-gray-700">Weekly</SelectItem>
                    <SelectItem value="monthly" className="text-gray-100 hover:bg-gray-700">Monthly</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <MetricChart 
                data={timeSeriesData.banRateOverTime} 
                timeFrame={banTimeFrame}
                color="#3b82f6"
                type="bar"
              />
            </Card>
            <Card className="bg-gray-800 p-4">
              <div className="flex justify-between items-center mb-4">
                <CardTitle className="text-lg text-gray-300">Messages Over Time</CardTitle>
                <Select value={messageTimeFrame} onValueChange={(value: TimeFrame) => setMessageTimeFrame(value)}>
                  <SelectTrigger className="w-32 bg-gray-800 border-gray-700 text-gray-100">
                    <SelectValue placeholder="Select timeframe" />
                  </SelectTrigger>
                  <SelectContent className="bg-gray-800 border-gray-700 text-gray-100">
                    <SelectItem value="daily" className="text-gray-100 hover:bg-gray-700">Daily</SelectItem>
                    <SelectItem value="weekly" className="text-gray-100 hover:bg-gray-700">Weekly</SelectItem>
                    <SelectItem value="monthly" className="text-gray-100 hover:bg-gray-700">Monthly</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <MetricChart 
                data={timeSeriesData.messageRateOverTime} 
                timeFrame={messageTimeFrame}
                color="#60a5fa"
                type="line"
              />
            </Card>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}