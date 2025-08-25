using System.Collections;
using System.Collections.Generic;
using UnityEngine;

public class P2IntroBehavior : StateMachineBehaviour
{
	public float jump_force_x;
	public float jump_force_y;
	public float time_until_collision_reactivation;
	private float ground_y_value;
    // OnStateEnter is called when a transition starts and the state machine starts to evaluate this state
    override public void OnStateEnter(Animator animator, AnimatorStateInfo stateInfo, int layerIndex)
    {
		animator.GetComponent<P2BossMethods>().deactivateCollisions();
        ground_y_value = animator.GetComponent<Renderer>().bounds.max.y + 0.05f;
		if (animator.GetComponent<P2BossMethods>().is_facing_left)
			animator.GetComponent<Rigidbody2D>().AddForce(new Vector2(-jump_force_x, jump_force_y));
		else
			animator.GetComponent<Rigidbody2D>().AddForce(new Vector2(jump_force_x, jump_force_y));
		animator.GetComponent<P2BossMethods>().playSound("P2Breakout");
		animator.GetComponent<P2BossMethods>().playTransmission();
		animator.GetComponent<P2BossMethods>().startBurstParticles();
	}

    // OnStateUpdate is called on each Update frame between OnStateEnter and OnStateExit callbacks
    override public void OnStateUpdate(Animator animator, AnimatorStateInfo stateInfo, int layerIndex)
    {
		if(time_until_collision_reactivation <= 0){
			//animator.GetComponent<P2BossMethods>().reactivateCollisions();
			if (animator.GetComponent<Renderer>().bounds.min.y <= ground_y_value){
				Debug.Log("Finished jumping");
				animator.SetTrigger("FinishedJumping");
				animator.GetComponent<Rigidbody2D>().isKinematic = true;
				animator.GetComponent<Rigidbody2D>().velocity = Vector3.zero;
				animator.GetComponent<Rigidbody2D>().angularVelocity = 0f;
				animator.GetComponent<P2BossMethods>().turnTowardsPlayer();
				animator.GetComponent<P2BossMethods>().startBurstParticles();
			}
		}
		else {
			time_until_collision_reactivation -= Time.deltaTime;
		}
    }

    // OnStateExit is called when a transition ends and the state machine finishes evaluating this state
    override public void OnStateExit(Animator animator, AnimatorStateInfo stateInfo, int layerIndex){
		animator.GetComponent<P2BossMethods>().reactivateCollisions();
    }

    // OnStateMove is called right after Animator.OnAnimatorMove()
    //override public void OnStateMove(Animator animator, AnimatorStateInfo stateInfo, int layerIndex)
    //{
    //    // Implement code that processes and affects root motion
    //}

    // OnStateIK is called right after Animator.OnAnimatorIK()
    //override public void OnStateIK(Animator animator, AnimatorStateInfo stateInfo, int layerIndex)
    //{
    //    // Implement code that sets up animation IK (inverse kinematics)
    //}
}
