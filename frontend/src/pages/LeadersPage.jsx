import LeaderBoard from '../components/LeaderBoard'
import HitProbChart from '../components/HitProbChart'

export default function LeadersPage() {
  return (
    <div className="space-y-8">
      <LeaderBoard />
      <HitProbChart />
    </div>
  )
}
