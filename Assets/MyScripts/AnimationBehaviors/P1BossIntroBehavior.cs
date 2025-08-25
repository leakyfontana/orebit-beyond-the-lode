using System.Collections;
using System.Collections.Generic;
using UnityEngine;

public class P1BossIntro : StateMachineBehaviour
{
	public float intro_time;
	[HideInInspector]
	public float intro_time_left;
	[HideInInspector]
	public Rigidbody2D rb;
	private float height; 
	
    // OnStateEnter is called when a transition starts and the state machine starts to evaluate this state
    override public void OnStateEnter(Animator animator, AnimatorStateInfo stateInfo, int layerIndex){
		rb = animator.GetComponent<Rigidbody2D>();
		height = animator.GetComponent<Renderer>().bounds.size.y * 1.5f;
		rb.position = new Vector2(rb.position.x, rb.position.y - height);
		intro_time_left = intro_time;
		animator.GetComponent<P1BossMethods>().playSound("P1Laugh");
		animator.GetComponent<P1BossMethods>().startSustainedParticles();
    }

    // OnStateUpdate is called on each Update frame between OnStateEnter and OnStateExit callbacks
    override public void OnStateUpdate(Animator animator, AnimatorStateInfo stateInfo, int layerIndex){
		intro_time_left -= Time.deltaTime;
		rb.position = new Vector2(rb.position.x, rb.position.y + ((height * Time.deltaTime)/intro_time));
		if(intro_time_left <= 0f){
			animator.SetTrigger("IntroIsFinished");
			animator.GetComponent<P1BossMethods>().playTransmission();
		}
    }
	
    // OnStateExit is called when a transition ends and the state machine finishes evaluating this state
    override public void OnStateExit(Animator animator, AnimatorStateInfo stateInfo, int layerIndex){
		animator.GetComponent<P1BossMethods>().stopSustainedParticles();
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
